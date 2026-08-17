from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

_SKIP = {"target", "dbt_packages", "node_modules"}
_SOURCE_GLOBS = ("*.sql", "*.yml", "*.yaml", "*.csv")
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


class ProjectParseError(Exception):
    pass


def dbt_command() -> list[str]:
    return shlex.split(os.environ.get("DBT_AGENT_TOOLS_DBT_CMD", "dbt"))


def _first_error(output: str) -> str:
    for line in output.splitlines():
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        info = evt.get("info", {})
        if info.get("level") == "error":
            return info.get("msg", "")[:1500]
    return output[-1500:]


class Project:
    def __init__(self, info: ProjectInfo, dbt_cmd: list[str] | None = None):
        self.info = info
        self.path = info.path
        self.dbt_cmd = dbt_cmd or dbt_command()

    def _manifest_path(self) -> Path:
        return self.path / "target" / "manifest.json"

    def _newest_source_mtime(self) -> float:
        newest = 0.0
        for pattern in _SOURCE_GLOBS:
            for f in self.path.rglob(pattern):
                parts = f.relative_to(self.path).parts
                if parts[0] in _SKIP or parts[0].startswith("."):
                    continue
                newest = max(newest, f.stat().st_mtime)
        return newest

    def parse(self) -> None:
        # dbt does not auto-read profiles.yml from the project dir; point it
        # there explicitly when the project ships one (see tests/conftest.py).
        env = os.environ
        if (self.path / "profiles.yml").exists():
            env = os.environ | {"DBT_PROFILES_DIR": str(self.path)}
        proc = subprocess.run(
            [*self.dbt_cmd, "parse", "--log-format", "json"],
            cwd=self.path,
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise ProjectParseError(_first_error(proc.stdout + proc.stderr))

    def manifest(self) -> dict:
        mp = self._manifest_path()
        if not mp.exists() or mp.stat().st_mtime < self._newest_source_mtime():
            self.parse()
        return json.loads(mp.read_text())
