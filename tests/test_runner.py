from pathlib import Path

from dbt_agent_tools.projects import Project, ProjectInfo
from dbt_agent_tools.runner import BUILD_SUBCOMMANDS, INSPECT_SUBCOMMANDS, run_dbt


def make(fixture_dir: Path) -> Project:
    return Project(ProjectInfo(name="fixture_proj", path=fixture_dir), ["dbt"])


def test_disallowed_subcommand_rejected(fixture_dir: Path) -> None:
    out = run_dbt(make(fixture_dir), "run-operation", INSPECT_SUBCOMMANDS)
    assert "not allowed" in out["error"]


def test_dangerous_args_rejected(fixture_dir: Path) -> None:
    out = run_dbt(make(fixture_dir), "ls", INSPECT_SUBCOMMANDS, args=["--project-dir", "/etc"])
    assert "error" in out


def test_seed_build_reports_counts(fixture_dir: Path) -> None:
    out = run_dbt(make(fixture_dir), "seed", BUILD_SUBCOMMANDS, select="seed_codes")
    assert out["counts"]["success"] == 1
    assert out["failures"] == []


def test_show_returns_capped_rows(fixture_dir: Path) -> None:
    run_dbt(make(fixture_dir), "seed", BUILD_SUBCOMMANDS, select="seed_codes")
    out = run_dbt(make(fixture_dir), "show", INSPECT_SUBCOMMANDS, select="seed_codes", limit=1)
    assert out["row_count"] == 1
    assert out["rows"][0]["code"] in {"W", "G"}


def test_ls_lists_nodes(fixture_dir: Path) -> None:
    out = run_dbt(make(fixture_dir), "ls", INSPECT_SUBCOMMANDS, select="stg_students")
    assert any("stg_students" in n for n in out["nodes"])


def test_failure_reports_first_error(fixture_dir: Path) -> None:
    # fct_enrollments' upstream views are never built in this suite, so a
    # bare run of it fails at runtime and must surface a failure entry
    out = run_dbt(make(fixture_dir), "run", BUILD_SUBCOMMANDS, select="fct_enrollments")
    assert out["status"] == "error"
    assert out["failures"] and "fct_enrollments" in out["failures"][0]["node"]
