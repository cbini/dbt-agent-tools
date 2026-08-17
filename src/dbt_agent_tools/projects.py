from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

_SKIP = {"target", "dbt_packages", "node_modules"}
_yaml_safe = YAML(typ="safe")


@dataclass
class ProjectInfo:
    name: str
    path: Path


def discover_projects(root: Path) -> dict[str, ProjectInfo]:
    projects: dict[str, ProjectInfo] = {}
    for pf in sorted(root.rglob("dbt_project.yml")):
        parts = pf.relative_to(root).parts[:-1]
        if any(p in _SKIP or p.startswith(".") for p in parts):
            continue
        with pf.open() as fh:
            data = _yaml_safe.load(fh) or {}
        name = data.get("name")
        if name:
            projects[name] = ProjectInfo(name=name, path=pf.parent)
    return projects
