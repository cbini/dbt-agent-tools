# dbt-agent-tools

A structured, queryable interface to dbt projects for Claude agents — progressive-disclosure dbt docs, guarded CLI execution, and YAML authoring tools.

## Install

Via Claude Code plugin marketplace:

```bash
claude plugin marketplace add cbini/dotclaude
claude plugin install dbt-agent-tools@dotclaude
```

Or manually, by adding to your `.mcp.json`:

```json
{
  "mcpServers": {
    "dbt-agent-tools": {
      "command": "uv",
      "args": ["run", "--project", "${CLAUDE_PLUGIN_ROOT}", "dbt-agent-tools"]
    }
  }
}
```

## Configuration

Set environment variables in your Claude Code settings or shell:

- **`DBT_AGENT_TOOLS_ROOT`** — workspace root (default: current working directory). For monorepos, set to the dbt project directory (e.g. `src/dbt/`).
- **`DBT_AGENT_TOOLS_DBT_CMD`** — dbt invocation command (default: `dbt`). For monorepos using `uv`, set to `uv run dbt`.

## Tools

| Tool | Purpose |
|------|---------|
| `list_projects` | List dbt projects in the workspace. |
| `list_nodes` | List models, tests, macros, and other nodes with optional filtering. |
| `get_node` | Retrieve node details (summary, columns, or full metadata). |
| `lineage` | Trace upstream/downstream dependencies for a node. |
| `resolve` | Map dbt node selector expressions to matching nodes. |
| `dbt_inspect` | Run dbt parse, compile, show, or ls commands for workspace inspection. |
| `dbt_build` | Execute dbt build, run, test, snapshot, or seed commands. |
| `write_yaml` | Create a new property YAML file (models, sources, metrics). |
| `edit_yaml` | Update an existing property YAML file. |

## YAML Authoring Contract

For validation and best practices on property YAML, see [`skills/authoring/references/meta-claude-contract.md`](skills/authoring/references/meta-claude-contract.md).

## Development

Install dependencies and run tests:

```bash
uv sync
uv run pytest
```

For detailed architecture and design rationale, see [`docs/superpowers/specs/2026-08-17-dbt-agent-tools-design.md`](docs/superpowers/specs/2026-08-17-dbt-agent-tools-design.md).
