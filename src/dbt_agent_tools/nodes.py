from __future__ import annotations

import difflib
import re

_REF_RE = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")
_SOURCE_RE = re.compile(r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")


def _all_named(manifest: dict):
    for uid, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") != "test":
            yield node.get("name", ""), uid, node
    for uid, node in manifest.get("sources", {}).items():
        yield f"{node['source_name']}.{node['name']}", uid, node
        yield node.get("name", ""), uid, node
    for uid, node in manifest.get("exposures", {}).items():
        yield node.get("name", ""), uid, node
    for uid, node in manifest.get("macros", {}).items():
        yield node.get("name", ""), uid, node


def find_node(manifest: dict, name: str) -> tuple[str, dict] | None:
    for candidate, uid, node in _all_named(manifest):
        if candidate == name:
            return uid, node
    return None


def suggest_names(manifest: dict, name: str) -> list[str]:
    names = sorted({n for n, _, _ in _all_named(manifest) if n})
    return difflib.get_close_matches(name, names, n=5, cutoff=0.6)


def resolve_ref(manifest: dict, text: str) -> tuple[str, dict] | None:
    if m := _SOURCE_RE.search(text):
        return find_node(manifest, f"{m.group(1)}.{m.group(2)}")
    if m := _REF_RE.search(text):
        return find_node(manifest, m.group(1))
    return find_node(manifest, text.strip())


def lineage(manifest: dict, unique_id: str, direction: str, depth: int) -> list[str]:
    graph = manifest["parent_map"] if direction == "upstream" else manifest["child_map"]
    seen: list[str] = []
    frontier = [unique_id]
    for _ in range(depth):
        nxt: list[str] = []
        for uid in frontier:
            for neighbor in graph.get(uid, []):
                if neighbor.startswith("test."):
                    continue
                if neighbor != unique_id and neighbor not in seen:
                    seen.append(neighbor)
                    nxt.append(neighbor)
        frontier = nxt
    return seen
