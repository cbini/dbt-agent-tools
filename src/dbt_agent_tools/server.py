from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from .nodes import find_node, lineage as _lineage, resolve_ref, suggest_names
from .projects import Project, ProjectParseError, discover_projects
from .runner import BUILD_SUBCOMMANDS, INSPECT_SUBCOMMANDS, run_dbt
from .tiers import render_node
from .yaml_edit import NoEntryError, edit_entry, write_entry

_CONTRACT = (Path(__file__).parent / "_contract.md").read_text()

mcp = FastMCP("dbt-agent-tools")
_projects: dict[str, Project] = {}


def reset(root: Path) -> None:
    _projects.clear()
    for name, info in discover_projects(root).items():
        _projects[name] = Project(info)


def _project(name: str | None) -> Project | str:
    if not _projects:
        return "error: no dbt projects found under the workspace root"
    if name is None and len(_projects) == 1:
        return next(iter(_projects.values()))
    if name in _projects:
        return _projects[name]
    return f"error: unknown project {name!r}; known: {sorted(_projects)}"


def _manifest_or_error(project: Project) -> dict | str:
    try:
        return project.manifest()
    except ProjectParseError as exc:
        return f"error: project unparseable: {exc}"


def _locate(name: str, project: str | None) -> tuple[Project, dict, str, dict] | str:
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    manifest = _manifest_or_error(proj)
    if isinstance(manifest, str):
        return manifest
    found = find_node(manifest, name)
    if not found:
        hints = suggest_names(manifest, name)
        return f"error: unknown node {name!r}; close matches: {hints}"
    return proj, manifest, found[0], found[1]


@mcp.tool(
    annotations={"title": "List dbt projects", "readOnlyHint": True, "idempotentHint": True}
)
def list_projects() -> str:
    """List discovered dbt projects with node counts. Read-only; does not parse."""
    out = []
    for name, proj in sorted(_projects.items()):
        out.append({"project": name, "path": str(proj.path)})
    return json.dumps(out)


@mcp.tool(
    annotations={"title": "List dbt nodes", "readOnlyHint": True, "idempotentHint": True}
)
def list_nodes(
    project: str | None = None,
    resource_type: Literal["model", "source", "seed", "snapshot", "exposure", "macro"] | None = None,
    pattern: str | None = None,
    stale_meta: bool = False,
) -> str:
    """List nodes: name, type, one-line description. Filter by resource_type,
    substring pattern, or stale_meta=true (meta.claude fingerprint mismatch).
    Returns names only — use get_node for detail."""
    from .tiers import claude_meta, is_stale

    proj = _project(project)
    if isinstance(proj, str):
        return proj
    manifest = _manifest_or_error(proj)
    if isinstance(manifest, str):
        return manifest
    rows = []
    sections = {"nodes": None, "sources": "source", "exposures": "exposure", "macros": "macro"}
    for section, forced_type in sections.items():
        for uid, node in manifest.get(section, {}).items():
            rtype = forced_type or node.get("resource_type")
            if rtype == "test":
                continue
            if resource_type and rtype != resource_type:
                continue
            if pattern and pattern not in node.get("name", ""):
                continue
            if stale_meta and is_stale(node) is not True:
                continue
            desc = (node.get("description") or "").strip().splitlines()
            rows.append(
                {"name": node.get("name"), "type": rtype, "description": desc[0] if desc else "",
                 "has_meta": bool(claude_meta(node))}
            )
    return json.dumps(rows)


@mcp.tool(
    annotations={"title": "Get node documentation", "readOnlyHint": True, "idempotentHint": True},
    description=(
        "Tiered documentation for one dbt node (model, source, seed, snapshot, "
        "exposure, macro). detail='summary' (default): derived facts (keys, joins, "
        "enums from tests) plus the meta.claude block. detail='columns': adds "
        "per-column docs; pass columns=[...] to restrict. detail='full': the whole "
        "property entry (expensive — prefer summary/columns). Returns documentation, "
        "not warehouse rows — use dbt_inspect with subcommand='show' for data.\n\n"
        "meta.claude field semantics:\n" + _CONTRACT
    ),
)
def get_node(
    name: str,
    detail: Literal["summary", "columns", "full"] = "summary",
    columns: list[str] | None = None,
    project: str | None = None,
) -> str:
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    _, manifest, uid, node = located
    checksum = node.get("checksum", {}).get("checksum", "")
    rendered = json.loads(render_node(manifest, uid, detail, columns))
    if checksum:
        rendered["checksum_prefix"] = checksum[:12]
    return json.dumps(rendered)


@mcp.tool(
    annotations={"title": "Node lineage", "readOnlyHint": True, "idempotentHint": True}
)
def lineage(
    name: str,
    direction: Literal["upstream", "downstream"] = "upstream",
    depth: int = 1,
    project: str | None = None,
) -> str:
    """Upstream or downstream node ids for a node, depth-capped (max 5).
    Names only — use get_node on results for detail."""
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    _, manifest, uid, _ = located
    return json.dumps(_lineage(manifest, uid, direction, min(depth, 5)))


@mcp.tool(
    annotations={"title": "Resolve ref/source", "readOnlyHint": True, "idempotentHint": True}
)
def resolve(ref_or_source: str, project: str | None = None) -> str:
    """Resolve a ref('x') / source('a','b') string or bare name to its node:
    unique_id, file path, relation name."""
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    manifest = _manifest_or_error(proj)
    if isinstance(manifest, str):
        return manifest
    found = resolve_ref(manifest, ref_or_source)
    if not found:
        return f"error: could not resolve {ref_or_source!r}"
    uid, node = found
    return json.dumps(
        {"unique_id": uid, "path": node.get("original_file_path"),
         "relation": node.get("relation_name")}
    )


@mcp.tool(
    annotations={"title": "dbt inspect (read-only)", "readOnlyHint": True}
)
def dbt_inspect(
    subcommand: Literal["parse", "compile", "show", "ls"],
    select: str | None = None,
    args: list[str] | None = None,
    limit: int = 20,
    project: str | None = None,
) -> str:
    """Run a no-side-effect dbt subcommand: parse, compile, show (rows, capped),
    ls. Never mutates the warehouse — use dbt_build for build/run/test."""
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    return json.dumps(run_dbt(proj, subcommand, INSPECT_SUBCOMMANDS, select, args, min(limit, 20)))


@mcp.tool(annotations={"title": "dbt build (mutates warehouse)"})
def dbt_build(
    subcommand: Literal["build", "run", "test", "snapshot", "seed"],
    select: str | None = None,
    args: list[str] | None = None,
    project: str | None = None,
) -> str:
    """Run a warehouse-mutating dbt subcommand: build, run, test, snapshot,
    seed. Returns pass/fail counts and first error per failing node.
    Read-only inspection belongs in dbt_inspect."""
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    return json.dumps(run_dbt(proj, subcommand, BUILD_SUBCOMMANDS, select, args))


@mcp.tool(
    annotations={"title": "Write property YAML entry", "destructiveHint": True}
)
def write_yaml(
    resource_type: Literal["model", "seed", "snapshot", "source", "exposure"],
    name: str,
    entry: dict,
    project: str | None = None,
) -> str:
    """Create or FULLY REPLACE a node's property YAML entry. Replacement is
    also how fields are removed. For partial updates use edit_yaml. The node
    must exist in the manifest (a new model's SQL file is picked up by the
    staleness auto-parse). Returns a unified diff — review it."""
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    proj, manifest, _, _ = located
    return write_entry(proj.path, manifest, resource_type, name, entry) or "no change"


@mcp.tool(annotations={"title": "Edit property YAML entry"})
def edit_yaml(
    resource_type: Literal["model", "seed", "snapshot", "source", "exposure"],
    name: str,
    fields: dict,
    project: str | None = None,
) -> str:
    """Merge a structured patch into an EXISTING property entry (columns merge
    by name). Errors if the node has no entry — use write_yaml to create one.
    Returns a unified diff — review it."""
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    proj, manifest, _, _ = located
    try:
        return edit_entry(proj.path, manifest, resource_type, name, fields) or "no change"
    except NoEntryError as exc:
        return f"error: {exc}"


def main() -> None:
    reset(Path(os.environ.get("DBT_AGENT_TOOLS_ROOT", ".")).resolve())
    mcp.run()


if __name__ == "__main__":
    main()
