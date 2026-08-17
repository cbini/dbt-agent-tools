from __future__ import annotations

import json
import subprocess
import threading
from collections import defaultdict
from pathlib import Path

from .projects import Project

INSPECT_SUBCOMMANDS = {"parse", "compile", "show", "ls"}
BUILD_SUBCOMMANDS = {"build", "run", "test", "snapshot", "seed"}
_FORBIDDEN_ARGS = {"--project-dir", "--profiles-dir"}

_locks: dict[Path, threading.Lock] = defaultdict(threading.Lock)


def _summarize_run_results(project: Project) -> dict:
    rr_path = project.path / "target" / "run_results.json"
    if not rr_path.exists():
        return {"status": "error", "failures": [{"node": "?", "message": "no run_results.json produced"}]}
    rr = json.loads(rr_path.read_text())
    counts: dict[str, int] = defaultdict(int)
    failures = []
    for result in rr.get("results", []):
        counts[result["status"]] += 1
        if result["status"] in {"error", "fail"}:
            failures.append(
                {"node": result.get("unique_id", "?"), "message": (result.get("message") or "")[:500]}
            )
    status = "success" if not failures else "error"
    return {
        "status": status,
        "counts": dict(counts),
        "failures": failures,
        "elapsed": rr.get("elapsed_time"),
    }


def run_dbt(
    project: Project,
    subcommand: str,
    allowed: set[str],
    select: str | None = None,
    args: list[str] | None = None,
    limit: int = 20,
) -> dict:
    if subcommand not in allowed:
        return {"error": f"subcommand {subcommand} not allowed; allowed: {sorted(allowed)}"}
    for arg in args or []:
        if not arg.startswith("--") or arg in _FORBIDDEN_ARGS:
            return {"error": f"argument {arg!r} not allowed"}

    cmd = [*project.dbt_cmd, subcommand]
    if select:
        cmd += ["--select", select]
    if subcommand == "show":
        cmd += ["--quiet", "--output", "json", "--limit", str(limit)]
    elif subcommand == "ls":
        cmd += ["--quiet"]
    cmd += args or []

    lock = _locks[project.path]
    if not lock.acquire(blocking=False):
        return {"error": "a dbt run is already in progress for this project"}
    try:
        proc = subprocess.run(cmd, cwd=project.path, env=project.env(), capture_output=True, text=True)
    finally:
        lock.release()

    if subcommand == "show":
        try:
            # observed dbt 1.12 shape: {"node": "<name>", "show": [{...}, ...]}
            payload = json.loads(proc.stdout)
            rows = payload.get("show", payload if isinstance(payload, list) else [])[:limit]
            return {"rows": rows, "row_count": len(rows)}
        except ValueError:
            return {"error": f"show failed: {proc.stdout[-500:] or proc.stderr[-500:]}"}
    if subcommand == "ls":
        # --quiet suppresses dbt's own log lines; still filter defensively
        # in case a future dbt version logs to stdout despite --quiet.
        nodes = [line.strip() for line in proc.stdout.splitlines() if "." in line]
        return {"nodes": nodes}
    if subcommand in {"parse", "compile"}:
        if proc.returncode == 0:
            return {"status": "success"}
        return {"status": "error", "message": (proc.stdout + proc.stderr)[-1000:]}
    return _summarize_run_results(project)
