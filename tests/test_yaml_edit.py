from pathlib import Path

import pytest
from ruamel.yaml import YAML

from dbt_agent_tools.yaml_edit import NoEntryError, edit_entry, write_entry

yaml_rt = YAML()


def _load(path: Path) -> dict:
    with path.open() as fh:
        return yaml_rt.load(fh)


def test_write_creates_file_for_undocumented_model(fixture_dir: Path, fixture_manifest: dict) -> None:
    diff = write_entry(
        fixture_dir,
        fixture_manifest,
        "model",
        "orphan_model",
        {"name": "orphan_model", "description": "Orphan.", "meta": {"claude": {"v": 1, "fingerprint": "abcdef123456"}}},
    )
    new_file = fixture_dir / "models/_orphan_model.yml"
    assert new_file.exists()
    assert "+    description: Orphan." in diff
    doc = _load(new_file)
    assert doc["models"][0]["name"] == "orphan_model"
    new_file.unlink()


def test_edit_merges_and_preserves_comment(fixture_dir: Path, fixture_manifest: dict) -> None:
    props = fixture_dir / "models/properties.yml"
    original = props.read_text()
    props.write_text("# fixture comment\n" + original)
    try:
        diff = edit_entry(
            fixture_dir,
            fixture_manifest,
            "model",
            "dim_schools",
            {"meta": {"claude": {"v": 1, "fingerprint": "111111111111", "grain": "one row per school"}}},
        )
        text = props.read_text()
        assert "# fixture comment" in text
        assert "grain: one row per school" in text
        assert "one row per school" in diff
        doc = _load(props)
        entry = next(m for m in doc["models"] if m["name"] == "dim_schools")
        assert entry["description"] == "One row per school."  # untouched field survives
        assert entry["columns"][0]["name"] == "school_id"
    finally:
        props.write_text(original)


def test_edit_merges_columns_by_name(fixture_dir: Path, fixture_manifest: dict) -> None:
    props = fixture_dir / "models/properties.yml"
    original = props.read_text()
    try:
        edit_entry(
            fixture_dir,
            fixture_manifest,
            "model",
            "stg_students",
            {"columns": [{"name": "exit_code", "meta": {"claude": {"gotchas": ["new gotcha"]}}}]},
        )
        doc = _load(props)
        entry = next(m for m in doc["models"] if m["name"] == "stg_students")
        exit_col = next(c for c in entry["columns"] if c["name"] == "exit_code")
        assert exit_col["meta"]["claude"]["gotchas"] == ["new gotcha"]
        assert exit_col["meta"]["claude"]["enum"]  # existing enum survives merge
        assert len([c for c in entry["columns"] if c["name"] == "exit_code"]) == 1
    finally:
        props.write_text(original)


def test_edit_without_entry_raises(fixture_dir: Path, fixture_manifest: dict) -> None:
    with pytest.raises(NoEntryError, match="write_yaml"):
        edit_entry(fixture_dir, fixture_manifest, "model", "orphan_model", {"description": "x"})
