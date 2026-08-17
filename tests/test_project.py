from __future__ import annotations

import time
from pathlib import Path

import pytest

from dbt_agent_tools.projects import Project, ProjectInfo, ProjectParseError


def make(fixture_dir: Path) -> Project:
    return Project(ProjectInfo(name="fixture_proj", path=fixture_dir), ["dbt"])


def test_manifest_loads(fixture_dir: Path) -> None:
    m = make(fixture_dir).manifest()
    assert "model.fixture_proj.stg_students" in m["nodes"]


def test_stale_manifest_triggers_reparse(fixture_dir: Path) -> None:
    p = make(fixture_dir)
    p.manifest()
    marker = fixture_dir / "models/new_model.sql"
    marker.write_text("select 2 as id\n")
    time.sleep(0.01)
    try:
        m = p.manifest()
        assert "model.fixture_proj.new_model" in m["nodes"]
    finally:
        marker.unlink()
        p.parse()  # restore manifest to fixture state for later tests


def test_parse_failure_raises_short_error(fixture_dir: Path) -> None:
    # NOTE: dbt parse never Jinja-renders model SQL bodies (verified against
    # dbt 1.12.2 with both --no-static-parser and --no-partial-parse), so an
    # undefined-macro call as written in the brief never raises. Swapped for
    # an unresolvable ref(), a real dbt-parse-time graph-resolution failure.
    p = make(fixture_dir)
    bad = fixture_dir / "models/broken.sql"
    bad.write_text("select {{ ref('does_not_exist') }}\n")
    try:
        with pytest.raises(ProjectParseError) as exc:
            p.parse()
        assert len(str(exc.value)) < 2000
        assert "does_not_exist" in str(exc.value)
    finally:
        bad.unlink()
        p.parse()
