import asyncio
import json
from pathlib import Path

from fastmcp import Client
from ruamel.yaml import YAML


def make_server(root: Path):
    import os

    os.environ["DBT_AGENT_TOOLS_ROOT"] = str(root)
    from dbt_agent_tools import server

    server.reset(root)  # re-discover projects for this root
    return server.mcp


def test_tool_inventory_and_annotations(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)

    async def check() -> None:
        async with Client(mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {
                "list_projects", "list_nodes", "get_node", "lineage",
                "resolve", "dbt_inspect", "dbt_build", "write_yaml", "edit_yaml",
            }
            for name in ("list_projects", "list_nodes", "get_node", "lineage", "resolve", "dbt_inspect"):
                assert tools[name].annotations.readOnlyHint is True, name
            assert tools["write_yaml"].annotations.destructiveHint is True
            assert "grain" in tools["get_node"].description  # contract embedded

    asyncio.run(check())


def test_get_node_roundtrip(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_node", {"name": "stg_students", "detail": "summary"}
            )
            payload = json.loads(result.content[0].text)
            assert payload["claude"]["grain"] == "one row per student"

            missing = await client.call_tool("get_node", {"name": "stg_studnts"})
            assert "stg_students" in missing.content[0].text  # suggestion

    asyncio.run(check())


def test_resolve_unknown_returns_suggestions(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("resolve", {"ref_or_source": "stg_studnts"})
            assert "stg_students" in result.content[0].text

    asyncio.run(check())


def test_list_projects_reports_counts(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("list_projects", {})
            projects = json.loads(result.content[0].text)
            fixture_proj = next(p for p in projects if p["project"] == "fixture_proj")
            assert fixture_proj["counts"]["model"] >= 4

    asyncio.run(check())


def test_write_yaml_replace_existing_exposure_touches_own_file(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)
    exposures = fixture_dir / "models/exposures.yml"
    original = exposures.read_text()
    new_file = fixture_dir / "models/_enrollment_dashboard.yml"

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "write_yaml",
                {
                    "resource_type": "exposure",
                    "name": "enrollment_dashboard",
                    "entry": {
                        "name": "enrollment_dashboard",
                        "type": "dashboard",
                        "owner": {"email": "nobody@example.com"},
                        "depends_on": ["ref('fct_enrollments')"],
                        "description": "Updated.",
                    },
                },
            )
            diff = result.content[0].text
            assert "models/exposures.yml" in diff
            assert not new_file.exists()

    try:
        asyncio.run(check())
    finally:
        exposures.write_text(original)
        if new_file.exists():
            new_file.unlink()


def test_edit_yaml_on_source_table(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)
    sources = fixture_dir / "models/sources.yml"
    original = sources.read_text()

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "edit_yaml",
                {
                    "resource_type": "source",
                    "name": "raw.students",
                    "fields": {"description": "Updated raw student rows."},
                },
            )
            diff = result.content[0].text
            assert "models/sources.yml" in diff
            assert "Updated raw student rows." in diff

    try:
        asyncio.run(check())
    finally:
        sources.write_text(original)


def test_write_yaml_creates_source_table_via_server(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)
    sources = fixture_dir / "models/sources.yml"
    original = sources.read_text()

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "write_yaml",
                {
                    "resource_type": "source",
                    "name": "raw.applications",
                    "entry": {"name": "applications", "description": "New raw table."},
                },
            )
            diff = result.content[0].text
            assert "models/sources.yml" in diff
            doc = YAML().load(sources.read_text())
            assert len(doc["sources"]) == 1
            raw = doc["sources"][0]
            assert raw["name"] == "raw"
            table_names = [t["name"] for t in raw["tables"]]
            assert "applications" in table_names
            assert "students" in table_names

    try:
        asyncio.run(check())
    finally:
        sources.write_text(original)


def test_list_projects_null_counts_when_never_parsed(tmp_path: Path) -> None:
    root = tmp_path / "unparsed_root"
    proj_dir = root / "unparsed_proj"
    proj_dir.mkdir(parents=True)
    (proj_dir / "dbt_project.yml").write_text("name: unparsed_proj\nversion: '1.0'\nprofile: x\n")
    mcp = make_server(root)

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("list_projects", {})
            projects = json.loads(result.content[0].text)
            assert projects == [{"project": "unparsed_proj", "path": str(proj_dir), "counts": None}]

    asyncio.run(check())
