import json

from dbt_agent_tools.tiers import claude_meta, is_stale, render_node


def test_summary_includes_meta_and_derived(fixture_manifest: dict) -> None:
    out = json.loads(render_node(fixture_manifest, "model.fixture_proj.stg_students", "summary", None))
    assert out["claude"]["grain"] == "one row per student"
    assert out["keys"] == ["student_id"]
    assert out["stale_meta"] is False
    assert "columns" not in out


def test_stale_flag(fixture_manifest: dict) -> None:
    node = fixture_manifest["nodes"]["model.fixture_proj.fct_enrollments"]
    assert is_stale(node) is True
    out = json.loads(render_node(fixture_manifest, "model.fixture_proj.fct_enrollments", "summary", None))
    assert out["stale_meta"] is True


def test_no_meta_no_stale_flag(fixture_manifest: dict) -> None:
    node = fixture_manifest["nodes"]["model.fixture_proj.orphan_model"]
    assert claude_meta(node) == {}
    assert is_stale(node) is None


def test_columns_tier_with_filter(fixture_manifest: dict) -> None:
    out = json.loads(
        render_node(fixture_manifest, "model.fixture_proj.stg_students", "columns", ["exit_code"])
    )
    cols = out["columns"]
    assert list(cols) == ["exit_code"]
    assert cols["exit_code"]["claude"]["enum"] == {"W": "withdrew", "G": "graduated"}


def test_summary_cap() -> None:
    manifest = {
        "nodes": {
            "model.p.big": {
                "resource_type": "model",
                "name": "big",
                "description": '"x": "y", ' * 500,
                "config": {"meta": {}},
                "refs": [],
                "columns": {},
            }
        },
        "parent_map": {},
        "child_map": {},
    }
    out_str = render_node(manifest, "model.p.big", "summary", None)
    out = json.loads(out_str)
    assert out["truncated"] == "[truncated — narrow your request]"
    assert len(out_str) <= 1200
