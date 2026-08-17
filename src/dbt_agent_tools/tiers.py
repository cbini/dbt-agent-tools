from __future__ import annotations

import json

from .derive import _attached_tests, derived_facts

_MARK = "[truncated — narrow your request]"
_CAPS = {"summary": 1200, "columns": 6000}


def claude_meta(node: dict) -> dict:
    for container in (node.get("config", {}).get("meta"), node.get("meta")):
        if container and "claude" in container:
            return container["claude"] or {}
    return {}


def is_stale(node: dict) -> bool | None:
    meta = claude_meta(node)
    checksum = node.get("checksum", {}).get("checksum")
    if not meta or not meta.get("fingerprint") or not checksum:
        return None
    return meta["fingerprint"] != checksum[:12]


def _get_node(manifest: dict, unique_id: str) -> dict:
    for section in ("nodes", "sources", "exposures", "macros"):
        if unique_id in manifest.get(section, {}):
            return manifest[section][unique_id]
    raise KeyError(unique_id)


def _column_entry(col: dict, manifest: dict, unique_id: str, col_name: str) -> dict:
    entry: dict = {}
    if t := col.get("data_type"):
        entry["type"] = t
    if d := (col.get("description") or "").strip():
        entry["description"] = d.splitlines()[0]
    for container in (col.get("config", {}).get("meta"), col.get("meta")):
        if container and "claude" in container:
            entry["claude"] = container["claude"] or {}
            break
    # Add column-bound tests
    tests = []
    for test in _attached_tests(manifest, unique_id):
        if test.get("column_name") == col_name:
            tm = test.get("test_metadata") or {}
            test_kind = tm.get("name") or test.get("name")
            tests.append(test_kind)
    if tests:
        entry["tests"] = tests
    return entry


def _cap(payload: dict, cap: int | None) -> str:
    text = json.dumps(payload, default=str)
    if cap and len(text) > cap:
        truncated = json.dumps({"truncated": _MARK, "content": text[: cap - 100]})
        return truncated
    return text


def render_node(
    manifest: dict, unique_id: str, detail: str, columns: list[str] | None
) -> str:
    node = _get_node(manifest, unique_id)
    payload: dict = {"name": node.get("name"), "resource_type": node.get("resource_type")}
    payload |= derived_facts(manifest, unique_id)
    if meta := claude_meta(node):
        payload["claude"] = meta
    if (stale := is_stale(node)) is not None:
        payload["stale_meta"] = stale

    if detail == "full":
        payload["description"] = node.get("description")
        payload["columns"] = node.get("columns", {})
        payload["meta"] = node.get("config", {}).get("meta") or node.get("meta", {})
        # Add all attached tests with column binding info
        tests = []
        for test in _attached_tests(manifest, unique_id):
            tm = test.get("test_metadata") or {}
            test_kind = tm.get("name") or test.get("name")
            if col := test.get("column_name"):
                tests.append(f"{test_kind} ({col})")
            else:
                tests.append(test_kind)
        if tests:
            payload["tests"] = tests
        return _cap(payload, None)

    if detail == "columns":
        cols = node.get("columns", {})
        wanted = columns if columns is not None else list(cols)
        payload["columns"] = {
            n: _column_entry(cols[n], manifest, unique_id, n) for n in wanted if n in cols
        }
    return _cap(payload, _CAPS[detail])
