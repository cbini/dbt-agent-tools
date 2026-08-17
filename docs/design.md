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

1. **Progressive disclosure of model documentation** — an agent retrieves
   exactly the tier of detail it needs, never a full YAML file or manifest.
2. **Token-lean, guarded dbt CLI execution** — structured results, safe
   invocation, no console floods.
3. **Structured YAML authoring** — create or update model property YAML
   without the agent reading or rewriting large files.
4. **A documentation channel optimized for agents** — a `meta.claude` block,
   token-dense and machine-shaped, kept separate from human-facing dbt
   properties.

**General-purpose:** works on any dbt project by reading `dbt_project.yml`
and `target/manifest.json` generically. No assumptions about repo layout
beyond "dbt projects live somewhere under the workspace root".

## Non-goals (v1)

- Write support for sources, exposures, seeds, or snapshots — models only.
- Per-column disclosure sub-tiers — the columns tier is already bounded.
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

### Data source: manifest-first

On startup the server discovers dbt projects (any directory containing
`dbt_project.yml` under the workspace root, skipping `target/`,
`dbt_packages/`, and hidden directories). Per project it lazily loads
`target/manifest.json` into server memory and answers every read tool from
it. The manifest is considered stale when it is older than the newest
model/YAML file in the project; the server then re-runs `dbt parse` before
answering.

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

| Tool | Returns |
| ---- | ------- |
| `list_projects()` | Discovered projects: name, path, model count |
| `list_models(project, subpath?, pattern?, stale_meta?)` | Model names + one-line summary each (tier 0) |
| `get_model(name, detail)` | Tiered detail — see below |
| `lineage(name, direction, depth=1)` | Node names only, depth-capped |
| `resolve(ref_or_source)` | ref/source string → model, file path, relation name |

`get_model` tiers:

- `summary` (default): the `meta.claude` block if present, else a derived
  fallback — first line of description, materialization, refs, declared
  grain. Includes a staleness flag when the fingerprint mismatches.
- `columns`: summary + column names, types (from manifest/catalog when
  available), first line of each column description, tests.
- `full`: the model's complete property entry. Explicitly opt-in; the tool
  description warns about cost.

### Exec tool (CLI wrap)

`dbt_run(project, subcommand, select?, args?)`

- Subcommand allowlist: `parse`, `compile`, `build`, `test`, `run`, `show`,
  `ls`. Nothing else.
- Server owns invocation: working directory, `--project-dir`, the project's
  Python environment (configurable command template, default `uv run dbt`).
- One-run-per-project lock — concurrent runs against one `target/` corrupt
  the partial-parse manifest.
- Output parsed from dbt's JSON log lines into: status, pass/warn/fail/skip
  counts, failing node names, first error message per failing node, elapsed
  time. `show` results row-capped (default 20).

### Write tool (development side)

`upsert_model_yaml(project, model, fields)`

- `fields` is a structured patch: any of `description`, `columns` (add or
  update by name), `tests`, `meta.claude`, `config` keys.
- Server edits with `ruamel.yaml` in round-trip mode — comments, key order,
  and anchors in untouched regions survive.
- If the model has no property entry, the server creates one (in the
  project's conventional properties file location, configurable pattern;
  default: sibling `_<model>.yml`).
- Returns a unified diff of the change — the diff is what the agent and the
  human review, not the file.

## The `meta.claude` contract

Two documentation channels with different audiences:

- **Vanilla dbt properties** (`description`, column docs) — written for
  humans: readable, simple. This tool reads but never densifies them.
- **`meta.claude`** — written for agents: token-dense, structured, no prose
  niceties. Not meant to be pleasant to read.

Schema (v1 — server validates only `v` and `fingerprint`; all other fields
are free-form by convention):

```yaml
meta:
  claude:
    v: 1
    fingerprint: a1b2c3d4e5f6 # sha256[:12] of the model's SQL file
    grain: one row per student per term
    keys: [student_number, academic_year, term]
    joins: { students: student_number, terms: [academic_year, term] }
    gotchas:
      - null term = year-long enrollment, not missing data
    see: [int_extracts__student_enrollments]
```

**Staleness:** `fingerprint` hashes the model's SQL source. On mismatch,
`get_model` flags the block stale and `list_models(stale_meta=true)`
enumerates regeneration targets.

**Authoring:** a companion skill (shipped in this plugin) drives generation —
the agent reads the model SQL and human docs, drafts the `meta.claude`
content, writes it via `upsert_model_yaml`, and a human reviews the PR diff.
Humans are never expected to hand-write token-optimized blocks; drift heals
because generation is re-runnable against stale fingerprints.

## Error handling

- Parse failure → return dbt's first error message, not a traceback; read
  tools degrade to "project unparseable: {error}".
- Unknown model → nearest-name suggestions.
- Write conflicts (file changed since manifest load) → re-read file, retry
  once, else fail with the diff that would have applied.
- All tool errors are structured strings sized for an agent transcript,
  never raw stack traces or log dumps.

## Testing

- A fixture dbt project in this repo (a handful of models exercising every
  tier: documented, undocumented, stale meta, no property file).
- pytest covers: tier outputs and their token bounds, staleness detection,
  ref/source resolution, YAML round-trip fidelity (comments survive an
  upsert), run-lock behavior, JSON-log parsing against recorded dbt output.
- Real-world validation: point the server at a large multi-project monorepo
  and spot-check; not part of CI here.

## Open questions (deferred to implementation plan)

- Exact token budget per tier (proposal: summary ≤ 300 tokens, columns
  ≤ 1,500, enforced by truncation with a "truncated" marker).
- `dbt show` inline `--limit` interaction with the row cap.
- Whether `list_projects` needs an explicit workspace-root argument or can
  always trust the server's launch cwd.
