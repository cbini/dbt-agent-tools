from __future__ import annotations

import re

_REF_IN_KWARG = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _attached_tests(manifest: dict, unique_id: str):
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") == "test" and node.get("attached_node") == unique_id:
            yield node


def derived_facts(manifest: dict, unique_id: str) -> dict:
    section = "sources" if unique_id.startswith("source.") else "nodes"
    node = manifest.get(section, {}).get(unique_id) or manifest.get("exposures", {}).get(unique_id, {})
    facts: dict = {}

    if desc := (node.get("description") or "").strip():
        facts["description"] = desc.splitlines()[0]
    if pk := node.get("primary_key"):
        facts["keys"] = pk
    if mat := node.get("config", {}).get("materialized"):
        facts["materialized"] = mat
    if access := node.get("access"):
        if access != "protected":
            facts["access"] = access
    if dep := node.get("deprecation_date"):
        facts["deprecation_date"] = dep

    refs = [r["name"] for r in node.get("refs", [])]
    refs += [f"{s[0]}.{s[1]}" for s in node.get("sources", [])]
    if refs:
        facts["refs"] = refs

    joins: dict = {}
    enums: dict = {}
    for test in _attached_tests(manifest, unique_id):
        tm = test.get("test_metadata") or {}
        kwargs = tm.get("kwargs", {})
        column = test.get("column_name") or kwargs.get("column_name")
        if tm.get("name") == "relationships":
            if m := _REF_IN_KWARG.search(kwargs.get("to", "")):
                joins[m.group(1)] = kwargs.get("field")
        elif tm.get("name") == "accepted_values" and column:
            enums[column] = kwargs.get("values", [])
    if joins:
        facts["joins"] = joins
    if enums:
        facts["enums"] = enums
    return facts
