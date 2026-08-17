from pathlib import Path

from dbt_agent_tools.projects import discover_projects


def make_project(root: Path, rel: str, name: str) -> None:
    d = root / rel
    d.mkdir(parents=True)
    (d / "dbt_project.yml").write_text(f"name: {name}\nprofile: fixture\n")


def test_discovers_projects_and_skips_junk(tmp_path: Path) -> None:
    make_project(tmp_path, "src/dbt/alpha", "alpha")
    make_project(tmp_path, "src/dbt/beta", "beta")
    # decoys that must be skipped
    make_project(tmp_path, "src/dbt/alpha/target/weird", "ghost1")
    make_project(tmp_path, "src/dbt/alpha/dbt_packages/dep", "ghost2")
    make_project(tmp_path, ".hidden/proj", "ghost3")

    found = discover_projects(tmp_path)

    assert set(found) == {"alpha", "beta"}
    assert found["alpha"].path == tmp_path / "src/dbt/alpha"


def test_empty_root(tmp_path: Path) -> None:
    assert discover_projects(tmp_path) == {}
