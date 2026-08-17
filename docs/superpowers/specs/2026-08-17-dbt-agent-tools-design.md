# dbt-agent-tools — design

**Status:** approved design, pre-implementation
**Date:** 2026-08-17
**Owner:** @cbini

## Problem

Agentic coding tools (Claude Code first) working in dbt projects burn context
on documentation retrieval. Model property YAML runs long — the motivating
monorepo carries ~135k lines of model YAML across 16 projects, with single
files of 1,000–4,000 lines — so answering "what's the grain of this model?"
means reading a file that costs more context than the task itself. Raw dbt CLI
output has the same problem: a `dbt build` floods the transcript with log
lines when the agent needs pass/fail counts and first errors.

Existing tools don't cover this:

- The official dbt MCP server is Cloud-API-backed: it doesn't see the local
  working tree (uncommitted changes), and its doc tools return whole payloads,
  not slices.
- Claude Code has no way to register a first-class custom tool; the extension
  points are MCP servers, skills, hooks, and plugins. The Agent SDK's
  custom-tool API only exists inside SDK-built applications.

## Goals

1. **Progressive disclosure of project documentation** — an agent retrieves
   exactly the tier of detail it needs, never a full YAML file or manifest.
   All dbt object types are in scope: models, sources, seeds, snapshots,
   exposures, macros, and tests.
2. **Token-lean, guarded dbt CLI execution** — structured results, safe
   invocation, no console floods.
3. **Structured YAML authoring** — create or update property YAML for any
   dbt object without the agent reading or rewriting large files.
4. **A documentation channel optimized for agents** — a `meta.claude` block,
   token-dense and machine-shaped, kept separate from human-facing dbt
   properties. In one line: a structured, queryable CLAUDE.md for dbt
   objects — retrieved per node on demand instead of loaded wholesale, and
   fingerprinted so it announces its own staleness.

**General-purpose:** works on any dbt project by reading `dbt_project.yml`
and `target/manifest.json` generically. No assumptions about repo layout
beyond "dbt projects live somewhere under the workspace root".

## Non-goals (v1)

- Caching beyond the in-process manifest — reload-on-stale is enough.
- Semantic layer, Cloud API, or warehouse access — other tools own those.
- Replacing the human docs workflow — vanilla dbt properties stay
  human-first; this tool never rewrites them for density.

## Architecture

One Python stdio MCP server (FastMCP). Distributed as a Claude Code plugin
(this repo carries `.claude-plugin/plugin.json`, a plugin-level `.mcp.json`,
and companion skills), listed in an external marketplace
(`cbini/dotclaude`) so installation is:

```bash
claude plugin marketplace add cbini/dotclaude
claude plugin install dbt-agent-tools@dotclaude
```

Local stdio is normally discouraged for distribution, but this server falls
under the sanctioned exception: it must run on the developer's machine (it
reads the uncommitted working tree and invokes the local dbt CLI), its
audience — dbt developers — has a Python toolchain by definition, and
Claude Code plugins are the supported channel for local stdio servers. MCPB
bundling is the upgrade path if non-developer users ever need it.

### Data source: manifest-first

On startup the server discovers dbt projects (any directory containing
`dbt_project.yml` under the workspace root, skipping `target/`,
`dbt_packages/`, and hidden directories). Per project it lazily loads
`target/manifest.json` into server memory and answers every read tool from
it. The manifest is considered stale when it is older than the newest
source or YAML file in the project; the server then re-runs `dbt parse`
before answering.

The agent never receives the manifest or a full YAML file — every tool
returns a bounded slice.

Rejected alternatives:

- **YAML-first indexing** — re-implements dbt's property merging and ref
  resolution.
- **Hybrid (manifest graph + raw YAML docs)** — two data paths whose seam
  breeds staleness bugs. Documented fallback if `dbt parse` latency proves
  painful on large projects.

## Tool surface

### Read tools (progressive disclosure)

Tools are node-generic: a "node" is any documented dbt object — model,
source table, seed, snapshot, exposure, macro, or singular test.

| Tool | Returns |
| ---- | ------- |
| `list_projects()` | Discovered projects: name, path, node counts by type |
| `list_nodes(project, resource_type?, subpath?, pattern?, stale_meta?)` | Node names + one-line summary each (tier 0) |
| `get_node(name, detail, columns?)` | Tiered detail — see below |
| `lineage(name, direction, depth=1)` | Node names only, depth-capped |
| `resolve(ref_or_source)` | ref/source string → node, file path, relation name |

`get_node` tiers. Every tier is **derived + curated**: the server composes
facts already encoded in standard dbt YAML (read from the manifest) and
layers the `meta.claude` block on top. `meta.claude` never restates what a
test or property already says.

Derived facts per node, all direct manifest reads (verified against a real
19MB manifest): keys (dbt precomputes `primary_key` per node from
uniqueness tests/constraints), join paths (test nodes with
`test_metadata.name == "relationships"` attached via `attached_node`), enum
values (`accepted_values` test kwargs), refs/sources, materialization,
`access`/`deprecation_date` when set, first line of description. Lineage
reads the precomputed `parent_map`/`child_map`; the write tools locate each
node's YAML via `patch_path`.

- `summary` (default): the derived facts above + the node's `meta.claude`
  block. Includes a staleness flag when the fingerprint mismatches.
- `columns`: summary + per-column detail — name, type (from
  manifest/catalog when available), first line of the column description,
  tests, and the column's own `meta.claude` block if present. The optional
  `columns` filter restricts output to named columns so wide models don't
  flood context.
- `full`: the node's complete property entry. Explicitly opt-in; the tool
  description warns about cost.

Tiers apply where they make sense per type: macros and exposures have no
columns tier; sources and seeds have no lineage upstream.

### Exec tools (CLI wrap)

Split read from write per MCP review criteria — one tool per side, never
mixed, so hosts can auto-approve the safe one:

- `dbt_inspect(project, subcommand, select?, args?)` — no-side-effect
  subcommands only: `parse`, `compile`, `show`, `ls`. Read-only annotated.
- `dbt_build(project, subcommand, select?, args?)` — warehouse-mutating
  subcommands: `build`, `run`, `test`, `snapshot`, `seed`. Requires host
  confirmation.

Both:

- Enforce their subcommand allowlist server-side. Nothing else runs.
- Server owns invocation: working directory, `--project-dir`, the project's
  Python environment (configurable command template, default `uv run dbt`).
- One-run-per-project lock — concurrent runs against one `target/` corrupt
  the partial-parse manifest.
- Output parsed from dbt's JSON log lines into: status, pass/warn/fail/skip
  counts, failing node names, first error message per failing node, elapsed
  time. `show` results row-capped (default 20).

### Write tools (development side)

Two tools mirroring the Write/Edit verbs agents already know:

- `write_yaml(project, resource_type, name, entry)` — create a node's
  property entry, or fully replace an existing one. Creating places the
  entry in the project's conventional properties file location
  (configurable pattern; default: sibling `_{name}.yml`). Full replacement
  is also how fields get removed.
- `edit_yaml(project, resource_type, name, fields)` — merge a structured
  patch into the existing entry: any of `description`, `columns` (add or
  update by name, each column accepting its own `meta.claude`), `tests`,
  `meta.claude`, `config` keys — whichever apply to the resource type. No
  existing entry is an error that points at `write_yaml`.

Both:

- Work for any resource type with property YAML: models, sources (source +
  table addressing), seeds, snapshots, exposures, macros, singular tests.
- Edit with `ruamel.yaml` in round-trip mode — comments, key order, and
  anchors in untouched regions survive.
- Return a unified diff of the change — the diff is what the agent and the
  human review, not the file.

### Tool annotations, schemas, and descriptions

- Every tool declares `title`, `readOnlyHint`, `destructiveHint`, and
  `idempotentHint`. The five read tools and `dbt_inspect` are
  `readOnlyHint: true`; `write_yaml` is `destructiveHint: true` (full
  replacement overwrites); `edit_yaml` and `dbt_build` are neither
  read-only nor destructive.
- Parameter schemas are tight: enums for `resource_type`, `detail`, and
  subcommands; bounded integers with defaults for `depth` and row caps;
  every parameter carries a description.
- Tool descriptions state what each tool does NOT do and name the sibling
  that does ("get_node returns documentation, not warehouse rows — use
  dbt_inspect with show for data"; "edit_yaml requires an existing entry —
  use write_yaml to create one").

## The `meta.claude` contract

Two documentation channels with different audiences:

- **Vanilla dbt properties** (`description`, column docs) — written for
  humans: readable, simple. This tool reads but never densifies them.
- **`meta.claude`** — written for agents: token-dense, structured, no prose
  niceties. Not meant to be pleasant to read.

`meta.claude` attaches at two levels: the node, and each column. It holds
only the **non-derivable residue** — context that standard dbt YAML cannot
express. Anything a test can encode belongs in a test (see the authoring
principle below): keys, join paths, and enum value lists are all derived,
never declared here.

Node-level schema (v1 — server validates only `v` and `fingerprint`; all
other fields are free-form by convention):

```yaml
models:
  - name: fct_enrollments
    meta:
      claude:
        v: 1
        fingerprint: a1b2c3d4e5f6 # prefix of dbt's own node checksum
        grain: one row per student per term # interpretation, not column list
        filters:
          - point-in-time queries need academic_year = current
          - active students = enrollment_status = 0
        gotchas:
          - null term = year-long enrollment, not missing data
          - for term-level counts use int_extracts__course_enrollments_by_term
    columns:
      - name: exit_code
        meta:
          claude:
            enum: { W: withdrew, G: graduated, T: transferred in-network }
            gotchas:
              - blank before 2021, not null-safe
```

Field notes:

- `v` versions the meta.claude contract itself (not the model — dbt's
  native model `versions:` govern the data contract and are unrelated).
- `grain` is optional prose interpretation; the column list itself derives
  from the uniqueness test.
- `filters` are canonical predicates an agent should apply when querying —
  not inferable from any standard property.
- `enum` maps values to **meanings**; the bare value list derives from an
  `accepted_values` test. Written only when meanings aren't obvious.
- Cross-references ("use X instead") are gotchas that name a node — no
  separate field.

**How agents learn the contract:** field semantics live in exactly one
place — the authoring skill's reference file
(`skills/authoring/references/meta-claude-contract.md`, version-keyed by
`v`) — and reach agents through the two surfaces they already load:

- **Read side** — the `get_node` tool description defines each field's
  meaning. It is generated from the contract file at release time, so it
  cannot drift. MCP tool descriptions sit in the agent's context for free.
- **Write side** — the skill loads the contract file on demand
  (skill-creator's progressive-disclosure pattern: SKILL.md stays short,
  references load when needed) plus style rules for token-dense phrasing.

Column-level blocks are fully free-form — no `v` or `fingerprint`; the
node-level fingerprint governs staleness for the whole entry. It is a
prefix of the `checksum` dbt already computes per node (sha256 of the
node's source file), captured at authoring time — the server compares it to
the current manifest checksum, computing nothing itself. Sources and
exposures, whose manifest entries carry no file checksum, fingerprint the
property entry itself.

**Staleness:** on fingerprint mismatch, `get_node` flags the block stale and
`list_nodes(stale_meta=true)` enumerates regeneration targets.

**Authoring:** a companion skill (shipped in this plugin) drives generation —
the agent reads the node source and human docs, drafts the `meta.claude`
content, writes it via `write_yaml`/`edit_yaml`, and a human reviews the PR
diff.
Humans are never expected to hand-write token-optimized blocks; drift heals
because generation is re-runnable against stale fingerprints.

**Tests-first principle:** if context can be encoded as a standard dbt test,
the authoring skill writes the test, not a meta field — a
`unique_combination_of_columns` test is both enforcement and documentation.
`meta.claude` gets only what tests and standard properties cannot say. This
eliminates the worst drift risk: meta disagreeing with tests.

The skill's frontmatter description is trigger-optimized per skill-creator
guidance (deliberately broad "use when" contexts — skills undertrigger by
default) and validated with a trigger eval set of should/shouldn't-trigger
prompts.

## Error handling

- Parse failure → return dbt's first error message, not a traceback; read
  tools degrade to "project unparseable: {error}".
- Unknown node → nearest-name suggestions.
- Write conflicts (file changed since manifest load) → re-read file, retry
  once, else fail with the diff that would have applied.
- All tool errors are structured strings sized for an agent transcript,
  never raw stack traces or log dumps.

## Testing

- A fixture dbt project in this repo exercising every tier and resource
  type: documented and undocumented models, a source, a seed, a snapshot,
  an exposure, stale meta, column-level meta, no property file.
- pytest covers: tier outputs and their token bounds, staleness detection,
  ref/source resolution, YAML round-trip fidelity (comments survive an
  an edit), run-lock behavior, JSON-log parsing against recorded dbt
  output.
- Real-world validation: point the server at a large multi-project monorepo
  and spot-check; not part of CI here.
- Authoring-skill evals (skill-creator loop) against the fixture project,
  with objective assertions: fingerprint present and current, no fact
  restated that a test already encodes, output parses against contract v1.

## Open questions (deferred to implementation plan)

- Exact token budget per tier (proposal: summary ≤ 300 tokens, columns
  ≤ 1,500, enforced by truncation with a "truncated" marker).
- `dbt show` inline `--limit` interaction with the row cap.
- Whether `list_projects` needs an explicit workspace-root argument or can
  always trust the server's launch cwd.
