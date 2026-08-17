# meta.claude contract (v1)

Agent-facing documentation embedded in dbt property YAML under
`meta.claude`. Token-dense, machine-shaped; humans review diffs, agents
read and write it. Never restate anything a dbt test or standard property
already encodes (keys, join paths, enum value lists are DERIVED from
tests — see tests-first rule below).

## Node-level fields

- `v` (required, int): contract version. Currently 1. Versions the
  contract itself, not the model (dbt model `versions:` are unrelated).
- `fingerprint` (required, str): first 12 chars of dbt's node
  `checksum.checksum` at authoring time. Mismatch with the current
  manifest checksum marks the block STALE — regenerate it.
- `grain` (optional, str): prose interpretation of row grain, e.g.
  "one row per student per term". The key column list derives from the
  uniqueness test; grain adds meaning the column names lack.
- `filters` (optional, list[str]): canonical predicates to apply when
  querying, e.g. "point-in-time queries need academic_year = current".
- `gotchas` (optional, list[str]): non-derivable caveats. Cross-references
  are gotchas that name a node ("for term counts use fct_terms instead").

## Column-level fields (free-form, no v/fingerprint)

- `enum` (optional, map): value -> meaning. Only when meaning is not
  obvious; the bare value list derives from an accepted_values test.
- `gotchas` (optional, list[str]): per-column caveats — encoding quirks,
  null semantics, historical breaks.

## Tests-first rule

If context can be a standard dbt test (`unique`, `not_null`,
`accepted_values`, `relationships`, `unique_combination_of_columns`),
WRITE THE TEST instead of a meta field. Tests are enforcement plus
documentation; meta that restates tests drifts.

## Style

- Telegraphic phrasing; no filler words; no full sentences required.
- Every item must be non-derivable from SQL, tests, or properties.
- Write via the write_yaml/edit_yaml tools; humans review the diff.
