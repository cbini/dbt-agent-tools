import asyncio
import json
from pathlib import Path

from fastmcp import Client


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
