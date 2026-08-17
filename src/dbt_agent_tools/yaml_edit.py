from __future__ import annotations

import difflib
import io
from pathlib import Path

from ruamel.yaml import YAML

from .nodes import find_node

yaml_rt = YAML()
yaml_rt.preserve_quotes = True
yaml_rt.indent(mapping=2, sequence=4, offset=2)

_SECTION = {
    "model": "models",
    "seed": "seeds",
    "snapshot": "snapshots",
    "source": "sources",
    "exposure": "exposures",
}


class NoEntryError(Exception):
    pass


def _patch_file(project_dir: Path, manifest: dict, name: str) -> Path | None:
    found = find_node(manifest, name)
    if not found:
        return None
    patch = found[1].get("patch_path")  # "project://models/x.yml"
    if not patch:
        return None
    return project_dir / patch.split("://", 1)[1]


def _default_file(project_dir: Path, manifest: dict, name: str) -> Path:
    found = find_node(manifest, name)
    if found and found[1].get("original_file_path"):
        return project_dir / Path(found[1]["original_file_path"]).parent / f"_{name}.yml"
    return project_dir / "models" / f"_{name}.yml"


def _dump(doc: dict) -> str:
    buf = io.StringIO()
    yaml_rt.dump(doc, buf)
    return buf.getvalue()


def _diff(path: Path, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
    )


def _deep_merge(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        for key, value in patch.items():
            base[key] = _deep_merge(base.get(key), value) if key in base else value
        return base
    if isinstance(base, list) and isinstance(patch, list) and all(
        isinstance(i, dict) and "name" in i for i in [*base, *patch]
    ):
        by_name = {i["name"]: i for i in base}
        for item in patch:
            if item["name"] in by_name:
                _deep_merge(by_name[item["name"]], item)
            else:
                base.append(item)
        return base
    return patch


def _find_entry(doc: dict, resource_type: str, name: str):
    section = doc.get(_SECTION[resource_type]) or []
    if resource_type == "source" and "." in name:
        source_name, table = name.split(".", 1)
        for src in section:
            if src.get("name") == source_name:
                for tbl in src.get("tables", []):
                    if tbl.get("name") == table:
                        return src.get("tables"), tbl
        return None, None
    for entry in section:
        if entry.get("name") == name:
            return section, entry
    return None, None


def write_entry(
    project_dir: Path, manifest: dict, resource_type: str, name: str, entry: dict
) -> str:
    path = _patch_file(project_dir, manifest, name) or _default_file(project_dir, manifest, name)
    if path.exists():
        with path.open() as fh:
            doc = yaml_rt.load(fh) or {}
        before = path.read_text()
    else:
        doc, before = {}, ""
    container, existing = _find_entry(doc, resource_type, name)
    if existing is not None:
        container[container.index(existing)] = entry
    else:
        doc.setdefault(_SECTION[resource_type], []).append(entry)
    after = _dump(doc)
    path.write_text(after)
    return _diff(path, before, after)


def edit_entry(
    project_dir: Path, manifest: dict, resource_type: str, name: str, fields: dict
) -> str:
    path = _patch_file(project_dir, manifest, name)
    if not path or not path.exists():
        raise NoEntryError(f"{name} has no property entry — use write_yaml to create one")
    with path.open() as fh:
        doc = yaml_rt.load(fh)
    before = path.read_text()
    _, existing = _find_entry(doc, resource_type, name)
    if existing is None:
        raise NoEntryError(f"{name} not found in {path.name} — use write_yaml to create it")
    _deep_merge(existing, fields)
    after = _dump(doc)
    path.write_text(after)
    return _diff(path, before, after)
