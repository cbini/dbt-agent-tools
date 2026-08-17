from __future__ import annotations

import json
import subprocess
import threading
import time
from collections import defaultdict
from pathlib import Path

from .projects import Project

INSPECT_SUBCOMMANDS = {"parse", "compile", "show", "ls"}
BUILD_SUBCOMMANDS = {"build", "run", "test", "snapshot", "seed"}
_FORBIDDEN_ARGS = {"--project-dir", "--profiles-dir"}

_locks: dict[Path, threading.Lock] = defaultdict(threading.Lock)


def _summarize_run_results(project: Project, started_at: float, proc: subprocess.CompletedProcess) -> dict:
    rr_path = project.path / "target" / "run_results.json"
    # A run_results.json from an EARLIER call (or none at all) if dbt failed
    # before its execution phase would otherwise be misread as this call's
    # result — only trust one written after this call started.
    if not rr_path.exists() or rr_path.stat().st_mtime < started_at:
        return {"status": "error", "message": (proc.stdout + proc.stderr)[-1000:]}
    rr = json.loads(rr_path.read_text())
    counts: dict[str, int] = {"success": 0, "error": 0, "skipped": 0, "warn": 0}
    failures = []
    for result in rr.get("results", []):
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        if result["status"] in {"error", "fail"}:
            failures.append(
                {"node": result.get("unique_id", "?"), "message": (result.get("message") or "")[:500]}
            )
    status = "success" if not failures else "error"
    return {
        "status": status,
        "counts": counts,
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
        if not arg.startswith("--") or arg.split("=", 1)[0] in _FORBIDDEN_ARGS:
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
        started_at = time.time()
        proc = subprocess.run(cmd, cwd=project.path, env=project.env(), capture_output=True, text=True)
        # run_results.json parsing must happen while still holding the lock —
        # a second call's dbt invocation can overwrite the file the instant
        # the lock is released, before this call gets to read it.
        if subcommand in BUILD_SUBCOMMANDS:
            return _summarize_run_results(project, started_at, proc)
    finally:
        lock.release()

    if subcommand == "show":
        try:
            # observed dbt 1.12 shape: {"node": "<name>", "show": [{...}, ...]}
            payload = json.loads(proc.stdout)
            rows = (payload.get("show", []) if isinstance(payload, dict) else payload)[:limit]
            return {"rows": rows, "row_count": len(rows)}
        except ValueError:
            return {"error": f"show failed: {proc.stdout[-500:] or proc.stderr[-500:]}"}
    if subcommand == "ls":
        # --quiet suppresses dbt's own log lines; still filter defensively
        # in case a future dbt version logs to stdout despite --quiet.
        nodes = [line.strip() for line in proc.stdout.splitlines() if "." in line]
        return {"nodes": nodes}
    # subcommand in {"parse", "compile"}
    if proc.returncode == 0:
        return {"status": "success"}
    return {"status": "error", "message": (proc.stdout + proc.stderr)[-1000:]}
