---
name: meta-claude-authoring
description: Generate or refresh meta.claude blocks — agent-optimized dbt documentation — for dbt models, sources, seeds, snapshots, and exposures. Use whenever the user asks to document a dbt model for Claude/agents, add or update meta.claude, fix stale meta.claude blocks (stale_meta flags from get_node or list_nodes), onboard a dbt project to dbt-agent-tools, or after changing a model's SQL when its meta fingerprint no longer matches. Also use when the user says "document this model", "add agent docs", or "refresh the claude meta".
---

# Authoring meta.claude blocks

Read `references/meta-claude-contract.md` FIRST — it defines every field,
the tests-first rule, and the style. Do not write a block without it.

## Workflow

1. Find targets: `list_nodes(project, stale_meta=true)` for refreshes, or
   the node the user named.
2. For each node, read: `get_node(name, detail="columns")`, then the SQL
   file itself (path from `resolve`). Read the human description — do not
   duplicate it; distill what it and the SQL cannot express.
3. Apply the tests-first rule: anything expressible as a dbt test goes in
   `data_tests` (via edit_yaml), not meta.
4. Draft the block per the contract. Set `fingerprint` to the first 12
   chars of the node's current checksum (shown by get_node as
   `checksum_prefix`; if absent, run dbt_inspect parse first).
5. Write with `edit_yaml` (existing entry) or `write_yaml` (new entry).
6. Show the returned diff to the user — the diff is the review surface.

## Do NOT

- Restate keys, join paths, or enum value lists — they derive from tests.
- Copy the human description into meta.
- Write prose sentences — telegraphic items only.
- Invent gotchas: every gotcha must trace to something in the SQL, the
  data, or the user's input.
