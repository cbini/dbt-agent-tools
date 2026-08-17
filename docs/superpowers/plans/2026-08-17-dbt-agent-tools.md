# dbt-agent-tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local stdio MCP server (plus companion authoring skill) that gives
agents progressive-disclosure access to dbt project documentation, guarded dbt
CLI execution, and structured YAML authoring, per the approved spec at
`docs/superpowers/specs/2026-08-17-dbt-agent-tools-design.md`.

**Architecture:** Manifest-first: every read tool answers from
`target/manifest.json`, auto-refreshed via `dbt parse` when stale. Tools return
bounded slices, never whole files. Writes go through `ruamel.yaml` round-trip
editing and return diffs. The `meta.claude` contract is single-sourced from the
authoring skill's reference file.

**Tech Stack:** Python ≥3.11, `fastmcp` v3 (jlowin), `ruamel.yaml`, pytest.
Dev-only: `dbt-core` + `dbt-duckdb` (to parse/run the fixture project). dbt is
NOT a runtime dependency — the server shells out to the target project's own
dbt.

## Global Constraints

- Repo: `/workspaces/dbt-agent-tools` (work directly on `main` — new repo, no
  branch policy yet).
- Package layout: `src/dbt_agent_tools/`; console script `dbt-agent-tools`.
- Tool names and allowlists exactly as specced: read tools `list_projects`,
  `list_nodes`, `get_node`, `lineage`, `resolve`, `dbt_inspect`
  (`parse|compile|show|ls`); write tools `write_yaml`, `edit_yaml`; exec
  `dbt_build` (`build|run|test|snapshot|seed`). Nothing else runs.
- Annotations: all read tools + `dbt_inspect` → `readOnlyHint: true`;
  `write_yaml` → `destructiveHint: true`; `edit_yaml`, `dbt_build` → neither.
  Every tool has `title`.
- Output caps (chars ≈ 4/token): summary tier ≤ 1200 chars, columns tier
  ≤ 6000 chars, `show` rows ≤ 20 — truncate with a literal
  `"[truncated — narrow your request]"` marker.
- `meta.claude` v1 node fields: `v`, `fingerprint`, `grain?`, `filters?`,
  `gotchas?`. Column fields: `enum?`, `gotchas?`. Fingerprint = first 12 chars
  of dbt's node `checksum.checksum`.
- dbt invocation command: `DBT_AGENT_TOOLS_DBT_CMD` environment variable,
  default `dbt` (monorepos set e.g. `uv run dbt` in plugin config).
- Errors are short strings sized for a transcript; unknown names get
  nearest-name suggestions; no tracebacks cross the tool boundary.
- Contract single-sourcing: canonical file is
  `skills/authoring/references/meta-claude-contract.md`; a generated copy at
  `src/dbt_agent_tools/_contract.md` feeds the `get_node` description; a test
  asserts the two are byte-identical (regenerate with
  `python scripts/sync_contract.py`).
- Every commit message uses conventional commits and ends with
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Scaffold and project discovery

**Files:**

- Create: `pyproject.toml`
- Create: `src/dbt_agent_tools/__init__.py`
- Create: `src/dbt_agent_tools/projects.py`
- Test: `tests/test_discovery.py`

**Interfaces:**

- Consumes: nothing (first task).
- Produces: `discover_projects(root: Path) -> dict[str, ProjectInfo]` where
  `ProjectInfo` is a dataclass with `name: str` and `path: Path`. Skips
  `target/`, `dbt_packages/`, `node_modules/`, and hidden directories.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "dbt-agent-tools"
version = "0.1.0"
description = "MCP server for agentic dbt development"
requires-python = ">=3.11"
dependencies = ["fastmcp>=3", "ruamel.yaml>=0.18"]

[project.scripts]
dbt-agent-tools = "dbt_agent_tools.server:main"

[dependency-groups]
dev = ["pytest>=8", "dbt-core>=1.8", "dbt-duckdb>=1.8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dbt_agent_tools"]
```

- [ ] **Step 2: Write the failing test**

`tests/test_discovery.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /workspaces/dbt-agent-tools && uv run pytest tests/test_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: dbt_agent_tools` (or ImportError).

- [ ] **Step 4: Write minimal implementation**

`src/dbt_agent_tools/__init__.py` (empty file).

`src/dbt_agent_tools/projects.py`:

```python
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
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/dbt_agent_tools tests/test_discovery.py
git commit -m "feat: scaffold package and dbt project discovery"
```

---

### Task 2: Fixture dbt project and manifest test fixture

**Files:**

- Create: `tests/fixture/dbt_project.yml`, `tests/fixture/profiles.yml`
- Create: `tests/fixture/seeds/seed_codes.csv`
- Create: `tests/fixture/models/sources.yml`
- Create: `tests/fixture/models/stg_students.sql`, `tests/fixture/models/dim_schools.sql`, `tests/fixture/models/fct_enrollments.sql`, `tests/fixture/models/orphan_model.sql`
- Create: `tests/fixture/models/properties.yml` (docs + tests + meta.claude,
  including one deliberately stale fingerprint and column-level meta)
- Create: `tests/fixture/models/exposures.yml`
- Create: `tests/conftest.py`
- Test: `tests/test_fixture.py`

**Interfaces:**

- Consumes: nothing.
- Produces: pytest session fixture `fixture_manifest` returning the parsed
  manifest `dict` of the fixture project, and session fixture `fixture_dir`
  returning its `Path`. The fixture project contains: a source
  (`raw.students`), a seed (`seed_codes`), four models (documented with
  current meta, documented with STALE fingerprint, documented without meta,
  undocumented), an exposure, and tests (`unique`,
  `dbt_utils`-free composite via `unique` on surrogate column is NOT used —
  plain `unique`, `not_null`, `accepted_values`, `relationships`).

- [ ] **Step 1: Write the fixture project files**

`tests/fixture/dbt_project.yml`:

```yaml
name: fixture_proj
version: "1.0.0"
profile: fixture
model-paths: [models]
seed-paths: [seeds]
```

`tests/fixture/profiles.yml`:

```yaml
fixture:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: target/fixture.duckdb
```

`tests/fixture/seeds/seed_codes.csv`:

```csv
code,meaning
W,withdrew
G,graduated
```

`tests/fixture/models/sources.yml`:

```yaml
sources:
  - name: raw
    schema: main
    description: Raw landing zone.
    tables:
      - name: students
        description: Raw student rows from the SIS.
```

`tests/fixture/models/stg_students.sql`:

```sql
select 1 as student_id, 'W' as exit_code, 10 as school_id
```

`tests/fixture/models/dim_schools.sql`:

```sql
select 10 as school_id, 'North' as school_name
```

`tests/fixture/models/fct_enrollments.sql`:

```sql
select s.student_id, s.school_id, s.exit_code
from {{ ref('stg_students') }} as s
inner join {{ ref('dim_schools') }} as d on s.school_id = d.school_id
```

`tests/fixture/models/orphan_model.sql`:

```sql
select 1 as id
```

`tests/fixture/models/properties.yml` (note: `stg_students` fingerprint is
`REPLACED_IN_CONFTEST` — the conftest fixture rewrites it to the real checksum
prefix after a first parse, so it is CURRENT; `fct_enrollments` keeps the
deliberately stale `000000000000`):

```yaml
models:
  - name: stg_students
    description: One row per student, cleaned from the raw SIS extract.
    meta:
      claude:
        v: 1
        fingerprint: REPLACED_IN_CONFTEST
        grain: one row per student
        filters:
          - active students only; withdrawn rows kept for history
        gotchas:
          - exit_code blank before 2021, not null-safe
    columns:
      - name: student_id
        description: Surrogate student key.
        data_tests:
          - unique
          - not_null
      - name: exit_code
        description: Exit status code.
        meta:
          claude:
            enum: { W: withdrew, G: graduated }
        data_tests:
          - accepted_values:
              values: [W, G]
      - name: school_id
        data_tests:
          - relationships:
              to: ref('dim_schools')
              field: school_id
  - name: dim_schools
    description: One row per school.
    columns:
      - name: school_id
        data_tests:
          - unique
          - not_null
  - name: fct_enrollments
    description: Student-school enrollment facts.
    meta:
      claude:
        v: 1
        fingerprint: "000000000000"
        grain: one row per student per school
```

`tests/fixture/models/exposures.yml`:

```yaml
exposures:
  - name: enrollment_dashboard
    type: dashboard
    owner:
      email: nobody@example.com
    depends_on:
      - ref('fct_enrollments')
```

- [ ] **Step 2: Write conftest with session-scoped parse**

`tests/conftest.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_SRC = Path(__file__).parent / "fixture"


def run_dbt_parse(project_dir: Path) -> None:
    subprocess.run(
        ["dbt", "parse", "--no-use-colors"],
        cwd=project_dir,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # copy so tests can mutate files without dirtying the repo
    dest = tmp_path_factory.mktemp("proj") / "fixture_proj"
    shutil.copytree(FIXTURE_SRC, dest)
    run_dbt_parse(dest)
    # pin stg_students fingerprint to the real checksum so its meta is CURRENT
    manifest = json.loads((dest / "target/manifest.json").read_text())
    checksum = manifest["nodes"]["model.fixture_proj.stg_students"]["checksum"]["checksum"]
    props = dest / "models/properties.yml"
    props.write_text(props.read_text().replace("REPLACED_IN_CONFTEST", checksum[:12]))
    run_dbt_parse(dest)
    return dest


@pytest.fixture(scope="session")
def fixture_manifest(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "target/manifest.json").read_text())
```

Also create `tests/fixture/.gitignore` containing `target/` and
`*.duckdb`, and set `DBT_PROFILES_DIR` via `tests/fixture/profiles.yml`
co-location (dbt reads profiles.yml from the project dir automatically when
present — verify; if not, export `DBT_PROFILES_DIR=.` in `run_dbt_parse`'s
subprocess environment).

- [ ] **Step 3: Write the failing test**

`tests/test_fixture.py`:

```python
def test_fixture_parses_expected_nodes(fixture_manifest: dict) -> None:
    nodes = fixture_manifest["nodes"]
    assert "model.fixture_proj.stg_students" in nodes
    assert "model.fixture_proj.orphan_model" in nodes
    assert "seed.fixture_proj.seed_codes" in nodes
    assert "source.fixture_proj.raw.students" in fixture_manifest["sources"]
    assert "exposure.fixture_proj.enrollment_dashboard" in fixture_manifest["exposures"]


def test_stg_students_meta_is_current(fixture_manifest: dict) -> None:
    node = fixture_manifest["nodes"]["model.fixture_proj.stg_students"]
    meta = node["config"]["meta"]["claude"]
    assert meta["fingerprint"] == node["checksum"]["checksum"][:12]


def test_fct_enrollments_meta_is_stale(fixture_manifest: dict) -> None:
    node = fixture_manifest["nodes"]["model.fixture_proj.fct_enrollments"]
    meta = node["config"]["meta"]["claude"]
    assert meta["fingerprint"] != node["checksum"]["checksum"][:12]
```

- [ ] **Step 4: Run, fix, verify pass**

Run: `uv run pytest tests/test_fixture.py -v`
Expected: 3 passed. (First run is slow — dbt parses twice. If meta lands under
`node["meta"]` instead of `node["config"]["meta"]` in the installed dbt
version, adjust the two tests to read
`node.get("config", {}).get("meta") or node.get("meta")` — and note the
location for Task 6.)

- [ ] **Step 5: Commit**

```bash
git add tests/fixture tests/conftest.py tests/test_fixture.py
git commit -m "test: fixture dbt project with parsed-manifest session fixture"
```

---

### Task 3: Manifest loading, staleness, auto-parse

**Files:**

- Modify: `src/dbt_agent_tools/projects.py`
- Test: `tests/test_project.py`

**Interfaces:**

- Consumes: `ProjectInfo`, `discover_projects` (Task 1); `fixture_dir` (Task 2).
- Produces:
  - `class Project(info: ProjectInfo, dbt_cmd: list[str])` with:
    - `manifest(self) -> dict` — loads `target/manifest.json`, re-running
      `dbt parse` first when the manifest is missing or older than the newest
      `*.sql`/`*.yml`/`*.csv` under the project (excluding `target/`,
      `dbt_packages/`).
    - `parse(self) -> None` — subprocess `[*dbt_cmd, "parse", "--log-format", "json"]`
      with `cwd=path`; on nonzero exit raises `ProjectParseError(first_error)`.
  - `class ProjectParseError(Exception)`.
  - `dbt_command() -> list[str]` — `shlex.split` of `DBT_AGENT_TOOLS_DBT_CMD`
    environment variable, default `["dbt"]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_project.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

import pytest

from dbt_agent_tools.projects import Project, ProjectInfo, ProjectParseError


def make(fixture_dir: Path) -> Project:
    return Project(ProjectInfo(name="fixture_proj", path=fixture_dir), ["dbt"])


def test_manifest_loads(fixture_dir: Path) -> None:
    m = make(fixture_dir).manifest()
    assert "model.fixture_proj.stg_students" in m["nodes"]


def test_stale_manifest_triggers_reparse(fixture_dir: Path) -> None:
    p = make(fixture_dir)
    p.manifest()
    marker = fixture_dir / "models/new_model.sql"
    marker.write_text("select 2 as id\n")
    time.sleep(0.01)
    try:
        m = p.manifest()
        assert "model.fixture_proj.new_model" in m["nodes"]
    finally:
        marker.unlink()
        p.parse()  # restore manifest to fixture state for later tests


def test_parse_failure_raises_short_error(fixture_dir: Path) -> None:
    p = make(fixture_dir)
    bad = fixture_dir / "models/broken.sql"
    bad.write_text("select {{ undefined_macro_xyz() }}\n")
    try:
        with pytest.raises(ProjectParseError) as exc:
            p.parse()
        assert len(str(exc.value)) < 2000
        assert "undefined_macro_xyz" in str(exc.value)
    finally:
        bad.unlink()
        p.parse()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_project.py -v`
Expected: FAIL — `ImportError: cannot import name 'Project'`.

- [ ] **Step 3: Implement**

Append to `src/dbt_agent_tools/projects.py`:

```python
import json
import os
import shlex
import subprocess

_SOURCE_GLOBS = ("*.sql", "*.yml", "*.yaml", "*.csv")


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
        proc = subprocess.run(
            [*self.dbt_cmd, "parse", "--log-format", "json"],
            cwd=self.path,
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_project.py tests/test_discovery.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dbt_agent_tools/projects.py tests/test_project.py
git commit -m "feat: manifest loading with staleness-triggered reparse"
```

---

### Task 4: Node lookup, resolve, lineage

**Files:**

- Create: `src/dbt_agent_tools/nodes.py`
- Test: `tests/test_nodes.py`

**Interfaces:**

- Consumes: manifest `dict` shape (Tasks 2–3).
- Produces:
  - `find_node(manifest, name: str) -> tuple[str, dict] | None` — searches
    `nodes` (models/seeds/snapshots/singular tests), `sources` (matching
    `source_name.table_name` or bare table name), `exposures`, `macros` by
    `name`; returns `(unique_id, node_dict)`.
  - `suggest_names(manifest, name: str) -> list[str]` — up to 5
    `difflib.get_close_matches` over all node names.
  - `resolve_ref(manifest, text: str) -> tuple[str, dict] | None` — accepts
    `ref('x')`, `source('a', 'b')` (single or double quotes), or a bare name.
  - `lineage(manifest, unique_id: str, direction: "upstream"|"downstream", depth: int) -> list[str]`
    — BFS over `parent_map`/`child_map`, deduplicated, excludes the start
    node, test nodes filtered out.

- [ ] **Step 1: Write the failing tests**

`tests/test_nodes.py`:

```python
from dbt_agent_tools.nodes import find_node, lineage, resolve_ref, suggest_names


def test_find_model(fixture_manifest: dict) -> None:
    uid, node = find_node(fixture_manifest, "stg_students")
    assert uid == "model.fixture_proj.stg_students"
    assert node["resource_type"] == "model"


def test_find_source_by_dotted_name(fixture_manifest: dict) -> None:
    uid, _ = find_node(fixture_manifest, "raw.students")
    assert uid == "source.fixture_proj.raw.students"


def test_find_exposure_and_seed(fixture_manifest: dict) -> None:
    assert find_node(fixture_manifest, "enrollment_dashboard")[0].startswith("exposure.")
    assert find_node(fixture_manifest, "seed_codes")[0].startswith("seed.")


def test_unknown_returns_none_with_suggestions(fixture_manifest: dict) -> None:
    assert find_node(fixture_manifest, "stg_studnts") is None
    assert "stg_students" in suggest_names(fixture_manifest, "stg_studnts")


def test_resolve_forms(fixture_manifest: dict) -> None:
    assert resolve_ref(fixture_manifest, "ref('stg_students')")[0].endswith(".stg_students")
    assert resolve_ref(fixture_manifest, 'source("raw", "students")')[0].startswith("source.")
    assert resolve_ref(fixture_manifest, "dim_schools")[0].endswith(".dim_schools")


def test_lineage_directions(fixture_manifest: dict) -> None:
    up = lineage(fixture_manifest, "model.fixture_proj.fct_enrollments", "upstream", 1)
    assert set(up) == {"model.fixture_proj.stg_students", "model.fixture_proj.dim_schools"}
    down = lineage(fixture_manifest, "model.fixture_proj.fct_enrollments", "downstream", 1)
    assert down == ["exposure.fixture_proj.enrollment_dashboard"]


def test_lineage_depth_capped(fixture_manifest: dict) -> None:
    down2 = lineage(fixture_manifest, "model.fixture_proj.stg_students", "downstream", 2)
    assert "exposure.fixture_proj.enrollment_dashboard" in down2
    down1 = lineage(fixture_manifest, "model.fixture_proj.stg_students", "downstream", 1)
    assert "exposure.fixture_proj.enrollment_dashboard" not in down1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_nodes.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/dbt_agent_tools/nodes.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_nodes.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dbt_agent_tools/nodes.py tests/test_nodes.py
git commit -m "feat: node lookup, ref/source resolution, depth-capped lineage"
```

---

### Task 5: Derived facts from tests and manifest fields

**Files:**

- Create: `src/dbt_agent_tools/derive.py`
- Test: `tests/test_derive.py`

**Interfaces:**

- Consumes: manifest shape; `find_node` (Task 4).
- Produces: `derived_facts(manifest, unique_id: str) -> dict` with keys (omit
  empty ones): `keys` (node `primary_key` list), `joins`
  (`{target_ref: field}` from relationships tests), `enums`
  (`{column: [values]}` from accepted_values tests), `refs` (names from
  `refs`/`sources`), `materialized`, `description` (first line only),
  `access`/`deprecation_date` when set.

- [ ] **Step 1: Write the failing tests**

`tests/test_derive.py`:

```python
from dbt_agent_tools.derive import derived_facts


def test_keys_from_primary_key(fixture_manifest: dict) -> None:
    facts = derived_facts(fixture_manifest, "model.fixture_proj.stg_students")
    assert facts["keys"] == ["student_id"]


def test_joins_from_relationships(fixture_manifest: dict) -> None:
    facts = derived_facts(fixture_manifest, "model.fixture_proj.stg_students")
    assert facts["joins"] == {"dim_schools": "school_id"}


def test_enums_from_accepted_values(fixture_manifest: dict) -> None:
    facts = derived_facts(fixture_manifest, "model.fixture_proj.stg_students")
    assert facts["enums"] == {"exit_code": ["W", "G"]}


def test_refs_and_materialization(fixture_manifest: dict) -> None:
    facts = derived_facts(fixture_manifest, "model.fixture_proj.fct_enrollments")
    assert set(facts["refs"]) == {"stg_students", "dim_schools"}
    assert facts["materialized"] == "view"


def test_description_first_line_only(fixture_manifest: dict) -> None:
    facts = derived_facts(fixture_manifest, "model.fixture_proj.stg_students")
    assert facts["description"] == "One row per student, cleaned from the raw SIS extract."


def test_empty_facts_omitted(fixture_manifest: dict) -> None:
    facts = derived_facts(fixture_manifest, "model.fixture_proj.orphan_model")
    assert "keys" not in facts
    assert "joins" not in facts
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_derive.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/dbt_agent_tools/derive.py`:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_derive.py -v`
Expected: 6 passed. (If `materialized` default differs, read the actual value
from the manifest and pin the assertion to it.)

- [ ] **Step 5: Commit**

```bash
git add src/dbt_agent_tools/derive.py tests/test_derive.py
git commit -m "feat: derive keys, joins, enums, refs from manifest tests"
```

---

### Task 6: meta.claude reading, staleness, tier rendering

**Files:**

- Create: `src/dbt_agent_tools/tiers.py`
- Test: `tests/test_tiers.py`

**Interfaces:**

- Consumes: `derived_facts` (Task 5); manifest shape.
- Produces:
  - `claude_meta(node: dict) -> dict` — reads `meta.claude` from
    `node["config"]["meta"]` falling back to `node["meta"]`; `{}` if absent.
  - `is_stale(node: dict) -> bool | None` — `None` when no meta or no
    checksum; else fingerprint != `checksum.checksum[:12]`.
  - `render_node(manifest, unique_id, detail: str, columns: list[str] | None) -> str`
    — JSON string. `summary`: derived facts + `claude` block + `stale_meta`
    flag, capped at 1200 chars. `columns`: adds per-column dicts
    (name, type, first-line description, tests, column `claude` meta), capped
    at 6000 chars. `full`: complete property-relevant fields (description,
    columns, config.meta, tests) uncapped. Truncation appends
    `"[truncated — narrow your request]"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tiers.py`:

```python
import json

from dbt_agent_tools.tiers import claude_meta, is_stale, render_node


def test_summary_includes_meta_and_derived(fixture_manifest: dict) -> None:
    out = json.loads(render_node(fixture_manifest, "model.fixture_proj.stg_students", "summary", None))
    assert out["claude"]["grain"] == "one row per student"
    assert out["keys"] == ["student_id"]
    assert out["stale_meta"] is False
    assert "columns" not in out


def test_stale_flag(fixture_manifest: dict) -> None:
    node = fixture_manifest["nodes"]["model.fixture_proj.fct_enrollments"]
    assert is_stale(node) is True
    out = json.loads(render_node(fixture_manifest, "model.fixture_proj.fct_enrollments", "summary", None))
    assert out["stale_meta"] is True


def test_no_meta_no_stale_flag(fixture_manifest: dict) -> None:
    node = fixture_manifest["nodes"]["model.fixture_proj.orphan_model"]
    assert claude_meta(node) == {}
    assert is_stale(node) is None


def test_columns_tier_with_filter(fixture_manifest: dict) -> None:
    out = json.loads(
        render_node(fixture_manifest, "model.fixture_proj.stg_students", "columns", ["exit_code"])
    )
    cols = out["columns"]
    assert list(cols) == ["exit_code"]
    assert cols["exit_code"]["claude"]["enum"] == {"W": "withdrew", "G": "graduated"}


def test_summary_cap() -> None:
    manifest = {
        "nodes": {
            "model.p.big": {
                "resource_type": "model",
                "name": "big",
                "description": "x" * 5000,
                "config": {"meta": {}},
                "refs": [],
                "columns": {},
            }
        },
        "parent_map": {},
        "child_map": {},
    }
    out = render_node(manifest, "model.p.big", "summary", None)
    assert len(out) <= 1250
    assert "[truncated — narrow your request]" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tiers.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/dbt_agent_tools/tiers.py`:

```python
from __future__ import annotations

import json

from .derive import derived_facts

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


def _column_entry(col: dict) -> dict:
    entry: dict = {}
    if t := col.get("data_type"):
        entry["type"] = t
    if d := (col.get("description") or "").strip():
        entry["description"] = d.splitlines()[0]
    if cm := (col.get("meta") or {}).get("claude"):
        entry["claude"] = cm
    return entry


def _cap(payload: dict, cap: int | None) -> str:
    text = json.dumps(payload, default=str)
    if cap and len(text) > cap:
        return text[: cap - len(_MARK) - 2] + " " + _MARK
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
        return _cap(payload, None)

    if detail == "columns":
        cols = node.get("columns", {})
        wanted = columns or list(cols)
        payload["columns"] = {n: _column_entry(cols[n]) for n in wanted if n in cols}
    return _cap(payload, _CAPS[detail])
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_tiers.py -v`
Expected: 5 passed. (If column meta lives under `col["config"]["meta"]` in the
installed dbt version, extend `_column_entry` to check both — mirror
`claude_meta`.)

- [ ] **Step 5: Commit**

```bash
git add src/dbt_agent_tools/tiers.py tests/test_tiers.py
git commit -m "feat: tiered node rendering with meta.claude and staleness flag"
```

---

### Task 7: YAML write and edit tools

**Files:**

- Create: `src/dbt_agent_tools/yaml_edit.py`
- Test: `tests/test_yaml_edit.py`

**Interfaces:**

- Consumes: manifest `patch_path` convention (`project://relative/path.yml`);
  fixture project (Task 2).
- Produces:
  - `write_entry(project_dir: Path, manifest: dict, resource_type: str, name: str, entry: dict) -> str`
    — creates or fully replaces the named entry; returns a unified diff. New
    entries for undocumented nodes go to a sibling `_{name}.yml`; nodes with a
    `patch_path` are replaced in place. `resource_type` one of: `model`,
    `seed`, `snapshot`, `source`, `exposure`. Source naming:
    `source_name.table_name` (replaces the table entry under the source).
  - `edit_entry(project_dir, manifest, resource_type, name, fields: dict) -> str`
    — deep-merges `fields` into the existing entry (columns merged by `name`);
    raises `NoEntryError("... use write_yaml")` when the node has no property
    entry.
  - Both preserve comments/order via `ruamel.yaml` round-trip mode.
  - Section key mapping: model→`models`, seed→`seeds`, snapshot→`snapshots`,
    source→`sources`, exposure→`exposures`.

- [ ] **Step 1: Write the failing tests**

`tests/test_yaml_edit.py`:

```python
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from dbt_agent_tools.yaml_edit import NoEntryError, edit_entry, write_entry

yaml_rt = YAML()


def _load(path: Path) -> dict:
    with path.open() as fh:
        return yaml_rt.load(fh)


def test_write_creates_file_for_undocumented_model(fixture_dir: Path, fixture_manifest: dict) -> None:
    diff = write_entry(
        fixture_dir,
        fixture_manifest,
        "model",
        "orphan_model",
        {"name": "orphan_model", "description": "Orphan.", "meta": {"claude": {"v": 1, "fingerprint": "abcdef123456"}}},
    )
    new_file = fixture_dir / "models/_orphan_model.yml"
    assert new_file.exists()
    assert "+    description: Orphan." in diff
    doc = _load(new_file)
    assert doc["models"][0]["name"] == "orphan_model"
    new_file.unlink()


def test_edit_merges_and_preserves_comment(fixture_dir: Path, fixture_manifest: dict) -> None:
    props = fixture_dir / "models/properties.yml"
    original = props.read_text()
    props.write_text("# fixture comment\n" + original)
    try:
        diff = edit_entry(
            fixture_dir,
            fixture_manifest,
            "model",
            "dim_schools",
            {"meta": {"claude": {"v": 1, "fingerprint": "111111111111", "grain": "one row per school"}}},
        )
        text = props.read_text()
        assert "# fixture comment" in text
        assert "grain: one row per school" in text
        assert "one row per school" in diff
        doc = _load(props)
        entry = next(m for m in doc["models"] if m["name"] == "dim_schools")
        assert entry["description"] == "One row per school."  # untouched field survives
        assert entry["columns"][0]["name"] == "school_id"
    finally:
        props.write_text(original)


def test_edit_merges_columns_by_name(fixture_dir: Path, fixture_manifest: dict) -> None:
    props = fixture_dir / "models/properties.yml"
    original = props.read_text()
    try:
        edit_entry(
            fixture_dir,
            fixture_manifest,
            "model",
            "stg_students",
            {"columns": [{"name": "exit_code", "meta": {"claude": {"gotchas": ["new gotcha"]}}}]},
        )
        doc = _load(props)
        entry = next(m for m in doc["models"] if m["name"] == "stg_students")
        exit_col = next(c for c in entry["columns"] if c["name"] == "exit_code")
        assert exit_col["meta"]["claude"]["gotchas"] == ["new gotcha"]
        assert exit_col["meta"]["claude"]["enum"]  # existing enum survives merge
        assert len([c for c in entry["columns"] if c["name"] == "exit_code"]) == 1
    finally:
        props.write_text(original)


def test_edit_without_entry_raises(fixture_dir: Path, fixture_manifest: dict) -> None:
    with pytest.raises(NoEntryError, match="write_yaml"):
        edit_entry(fixture_dir, fixture_manifest, "model", "orphan_model", {"description": "x"})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_yaml_edit.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/dbt_agent_tools/yaml_edit.py`:

```python
from __future__ import annotations

import difflib
import io
from pathlib import Path

from ruamel.yaml import YAML

from .nodes import find_node

yaml_rt = YAML()
yaml_rt.preserve_quotes = True

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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_yaml_edit.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dbt_agent_tools/yaml_edit.py tests/test_yaml_edit.py
git commit -m "feat: round-trip YAML write and edit with diff output"
```

---

### Task 8: dbt runner with allowlists, lock, structured results

**Files:**

- Create: `src/dbt_agent_tools/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**

- Consumes: `Project` (Task 3).
- Produces:
  - `INSPECT_SUBCOMMANDS = {"parse", "compile", "show", "ls"}`,
    `BUILD_SUBCOMMANDS = {"build", "run", "test", "snapshot", "seed"}`.
  - `run_dbt(project: Project, subcommand: str, allowed: set[str], select: str | None = None, args: list[str] | None = None, limit: int = 20) -> dict`
    — rejects subcommands not in `allowed` with
    `{"error": "subcommand X not allowed; allowed: ..."}`; holds a per-project
    `threading.Lock` (concurrent second call returns
    `{"error": "a dbt run is already in progress for this project"}`
    immediately via non-blocking acquire); rejects `args` entries that don't
    start with `--` or that are `--project-dir`/`--profiles-dir`.
  - Result dict for build-family: `{"status", "counts": {"success": n, "error": n, "skipped": n, "warn": n}, "failures": [{"node", "message"}], "elapsed"}`
    parsed from `target/run_results.json`.
  - For `show`: `{"rows": [...], "row_count": n}` parsed from
    `--quiet --output json` stdout, rows capped at `limit`.
  - For `ls`: `{"nodes": [...]}` from stdout lines. For `parse`/`compile`:
    `{"status": "success"}` or error.

- [ ] **Step 1: Write the failing tests**

`tests/test_runner.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/dbt_agent_tools/runner.py`:

```python
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
    cmd += args or []

    lock = _locks[project.path]
    if not lock.acquire(blocking=False):
        return {"error": "a dbt run is already in progress for this project"}
    try:
        proc = subprocess.run(cmd, cwd=project.path, capture_output=True, text=True)
    finally:
        lock.release()

    if subcommand == "show":
        try:
            payload = json.loads(proc.stdout)
            rows = payload.get("show", payload if isinstance(payload, list) else [])[:limit]
            return {"rows": rows, "row_count": len(rows)}
        except ValueError:
            return {"error": f"show failed: {proc.stdout[-500:] or proc.stderr[-500:]}"}
    if subcommand == "ls":
        nodes = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return {"nodes": nodes}
    if subcommand in {"parse", "compile"}:
        if proc.returncode == 0:
            return {"status": "success"}
        return {"status": "error", "message": (proc.stdout + proc.stderr)[-1000:]}
    return _summarize_run_results(project)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_runner.py -v`
Expected: 6 passed. (dbt `show` JSON stdout shape varies by version — if
`json.loads(proc.stdout)` fails on a valid run, print the stdout once, adjust
the payload extraction to the observed shape, and pin the test to it. `ls`
may emit non-node log lines; filter to lines containing `.`.)

- [ ] **Step 5: Commit**

```bash
git add src/dbt_agent_tools/runner.py tests/test_runner.py
git commit -m "feat: guarded dbt runner with lock and structured results"
```

---

### Task 9: Contract doc, sync script, authoring skill

**Files:**

- Create: `skills/authoring/references/meta-claude-contract.md`
- Create: `skills/authoring/SKILL.md`
- Create: `scripts/sync_contract.py`
- Create: `src/dbt_agent_tools/_contract.md` (generated)
- Create: `skills/authoring/evals/trigger_evals.json`
- Test: `tests/test_contract.py`

**Interfaces:**

- Consumes: nothing from code (documentation task with a sync check).
- Produces: `src/dbt_agent_tools/_contract.md`, byte-identical to
  `skills/authoring/references/meta-claude-contract.md`; Task 10 embeds it in
  the `get_node` description via
  `(Path(__file__).parent / "_contract.md").read_text()`.

- [ ] **Step 1: Write the contract reference file**

`skills/authoring/references/meta-claude-contract.md`:

```markdown
# meta.claude contract (v1)

Agent-facing documentation embedded in dbt property YAML under
`meta.claude`. Token-dense, machine-shaped; humans review diffs, agents
read and write it. Never restate anything a dbt test or standard property
already encodes (keys, join paths, enum value lists are DERIVED from
tests — see tests-first rule below).

## Node-level fields

- `v` (required, int): contract version. Currently 1. Versions the
  contract itself, not the model (dbt model `versions:` are unrelated).
- `fingerprint` (required, str): first 12 chars of dbt's node
  `checksum.checksum` at authoring time. Mismatch with the current
  manifest checksum marks the block STALE — regenerate it.
- `grain` (optional, str): prose interpretation of row grain, e.g.
  "one row per student per term". The key column list derives from the
  uniqueness test; grain adds meaning the column names lack.
- `filters` (optional, list[str]): canonical predicates to apply when
  querying, e.g. "point-in-time queries need academic_year = current".
- `gotchas` (optional, list[str]): non-derivable caveats. Cross-references
  are gotchas that name a node ("for term counts use fct_terms instead").

## Column-level fields (free-form, no v/fingerprint)

- `enum` (optional, map): value -> meaning. Only when meaning is not
  obvious; the bare value list derives from an accepted_values test.
- `gotchas` (optional, list[str]): per-column caveats — encoding quirks,
  null semantics, historical breaks.

## Tests-first rule

If context can be a standard dbt test (`unique`, `not_null`,
`accepted_values`, `relationships`, `unique_combination_of_columns`),
WRITE THE TEST instead of a meta field. Tests are enforcement plus
documentation; meta that restates tests drifts.

## Style

- Telegraphic phrasing; no filler words; no full sentences required.
- Every item must be non-derivable from SQL, tests, or properties.
- Write via the write_yaml/edit_yaml tools; humans review the diff.
```

- [ ] **Step 2: Write the sync script and generated copy**

`scripts/sync_contract.py`:

```python
"""Copy the canonical contract file into the package. Run after editing it."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "skills/authoring/references/meta-claude-contract.md"
DEST = ROOT / "src/dbt_agent_tools/_contract.md"

DEST.write_text(SRC.read_text())
print(f"synced {SRC} -> {DEST}")
```

Run: `uv run python scripts/sync_contract.py` (creates
`src/dbt_agent_tools/_contract.md`).

- [ ] **Step 3: Write the failing sync test, verify it passes**

`tests/test_contract.py`:

```python
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_packaged_contract_matches_canonical() -> None:
    canonical = ROOT / "skills/authoring/references/meta-claude-contract.md"
    packaged = ROOT / "src/dbt_agent_tools/_contract.md"
    assert packaged.read_text() == canonical.read_text(), (
        "run: uv run python scripts/sync_contract.py"
    )
```

Run: `uv run pytest tests/test_contract.py -v` — expected PASS (sync already
run). Then temporarily append a char to the canonical file, re-run to see it
FAIL, revert, re-run to PASS (verifies the test detects drift).

- [ ] **Step 4: Write the authoring skill**

`skills/authoring/SKILL.md`:

```markdown
---
name: meta-claude-authoring
description: Generate or refresh meta.claude blocks — agent-optimized dbt documentation — for dbt models, sources, seeds, snapshots, and exposures. Use whenever the user asks to document a dbt model for Claude/agents, add or update meta.claude, fix stale meta (stale_meta flags from get_node or list_nodes), onboard a dbt project to dbt-agent-tools, or after changing a model's SQL when its meta fingerprint no longer matches. Also use when the user says "document this model", "add agent docs", or "refresh the claude meta".
---

# Authoring meta.claude blocks

Read `references/meta-claude-contract.md` FIRST — it defines every field,
the tests-first rule, and the style. Do not write a block without it.

## Workflow

1. Find targets: `list_nodes(project, stale_meta=true)` for refreshes, or
   the node the user named.
2. For each node, read: `get_node(name, detail="columns")`, then the SQL
   file itself (path from `resolve`). Read the human description — do not
   duplicate it; distill what it and the SQL cannot express.
3. Apply the tests-first rule: anything expressible as a dbt test goes in
   `data_tests` (via edit_yaml), not meta.
4. Draft the block per the contract. Set `fingerprint` to the first 12
   chars of the node's current checksum (shown by get_node as
   `checksum_prefix`; if absent, run dbt_inspect parse first).
5. Write with `edit_yaml` (existing entry) or `write_yaml` (new entry).
6. Show the returned diff to the user — the diff is the review surface.

## Do NOT

- Restate keys, join paths, or enum value lists — they derive from tests.
- Copy the human description into meta.
- Write prose sentences — telegraphic items only.
- Invent gotchas: every gotcha must trace to something in the SQL, the
  data, or the user's input.
```

- [ ] **Step 5: Write the starter trigger eval set**

`skills/authoring/evals/trigger_evals.json`:

```json
[
  { "query": "add a meta.claude block to stg_powerschool__students", "should_trigger": true },
  { "query": "get_node says fct_enrollments has stale_meta true, fix it", "should_trigger": true },
  { "query": "document our int_extracts models so claude stops misreading the grain", "should_trigger": true },
  { "query": "onboard the finance dbt project to dbt-agent-tools", "should_trigger": true },
  { "query": "i just rewrote fct_attendance.sql, refresh its agent docs", "should_trigger": true },
  { "query": "write a description for stg_students for our dbt docs site", "should_trigger": false },
  { "query": "add a unique test on student_id in stg_students", "should_trigger": false },
  { "query": "why is dbt build failing on fct_enrollments", "should_trigger": false },
  { "query": "update CLAUDE.md with what we learned this session", "should_trigger": false }
]
```

- [ ] **Step 6: Run full suite and commit**

Run: `uv run pytest -v` — expected: all tasks' tests pass.

```bash
git add skills scripts/sync_contract.py src/dbt_agent_tools/_contract.md tests/test_contract.py
git commit -m "feat: meta.claude contract, sync script, authoring skill"
```

---

### Task 10: MCP server assembly

**Files:**

- Create: `src/dbt_agent_tools/server.py`
- Test: `tests/test_server.py`

**Interfaces:**

- Consumes: everything from Tasks 1–9.
- Produces: FastMCP app `mcp` exposing exactly 9 tools (`list_projects`,
  `list_nodes`, `get_node`, `lineage`, `resolve`, `dbt_inspect`, `dbt_build`,
  `write_yaml`, `edit_yaml`) and `main()` console entry point. Workspace root
  = `DBT_AGENT_TOOLS_ROOT` environment variable, default cwd. All tool
  returns are strings (JSON or diff); all errors are short strings starting
  with `"error: "`.

- [ ] **Step 1: Write the failing test**

`tests/test_server.py`:

```python
import asyncio
import json
from pathlib import Path

from fastmcp import Client


def make_server(root: Path):
    import os

    os.environ["DBT_AGENT_TOOLS_ROOT"] = str(root)
    from dbt_agent_tools import server

    server.reset(root)  # re-discover projects for this root
    return server.mcp


def test_tool_inventory_and_annotations(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)

    async def check() -> None:
        async with Client(mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert set(tools) == {
                "list_projects", "list_nodes", "get_node", "lineage",
                "resolve", "dbt_inspect", "dbt_build", "write_yaml", "edit_yaml",
            }
            for name in ("list_projects", "list_nodes", "get_node", "lineage", "resolve", "dbt_inspect"):
                assert tools[name].annotations.readOnlyHint is True, name
            assert tools["write_yaml"].annotations.destructiveHint is True
            assert "grain" in tools["get_node"].description  # contract embedded

    asyncio.run(check())


def test_get_node_roundtrip(fixture_dir: Path) -> None:
    mcp = make_server(fixture_dir.parent)

    async def check() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_node", {"name": "stg_students", "detail": "summary"}
            )
            payload = json.loads(result.content[0].text)
            assert payload["claude"]["grain"] == "one row per student"

            missing = await client.call_tool("get_node", {"name": "stg_studnts"})
            assert "stg_students" in missing.content[0].text  # suggestion

    asyncio.run(check())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — no `server` module.

- [ ] **Step 3: Implement**

`src/dbt_agent_tools/server.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from .nodes import find_node, lineage as _lineage, resolve_ref, suggest_names
from .projects import Project, ProjectParseError, discover_projects
from .runner import BUILD_SUBCOMMANDS, INSPECT_SUBCOMMANDS, run_dbt
from .tiers import render_node
from .yaml_edit import NoEntryError, edit_entry, write_entry

_CONTRACT = (Path(__file__).parent / "_contract.md").read_text()

mcp = FastMCP("dbt-agent-tools")
_projects: dict[str, Project] = {}


def reset(root: Path) -> None:
    _projects.clear()
    for name, info in discover_projects(root).items():
        _projects[name] = Project(info)


def _project(name: str | None) -> Project | str:
    if not _projects:
        return "error: no dbt projects found under the workspace root"
    if name is None and len(_projects) == 1:
        return next(iter(_projects.values()))
    if name in _projects:
        return _projects[name]
    return f"error: unknown project {name!r}; known: {sorted(_projects)}"


def _manifest_or_error(project: Project) -> dict | str:
    try:
        return project.manifest()
    except ProjectParseError as exc:
        return f"error: project unparseable: {exc}"


def _locate(name: str, project: str | None) -> tuple[Project, dict, str, dict] | str:
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    manifest = _manifest_or_error(proj)
    if isinstance(manifest, str):
        return manifest
    found = find_node(manifest, name)
    if not found:
        hints = suggest_names(manifest, name)
        return f"error: unknown node {name!r}; close matches: {hints}"
    return proj, manifest, found[0], found[1]


@mcp.tool(
    annotations={"title": "List dbt projects", "readOnlyHint": True, "idempotentHint": True}
)
def list_projects() -> str:
    """List discovered dbt projects with node counts. Read-only; does not parse."""
    out = []
    for name, proj in sorted(_projects.items()):
        out.append({"project": name, "path": str(proj.path)})
    return json.dumps(out)


@mcp.tool(
    annotations={"title": "List dbt nodes", "readOnlyHint": True, "idempotentHint": True}
)
def list_nodes(
    project: str | None = None,
    resource_type: Literal["model", "source", "seed", "snapshot", "exposure", "macro"] | None = None,
    pattern: str | None = None,
    stale_meta: bool = False,
) -> str:
    """List nodes: name, type, one-line description. Filter by resource_type,
    substring pattern, or stale_meta=true (meta.claude fingerprint mismatch).
    Returns names only — use get_node for detail."""
    from .tiers import claude_meta, is_stale

    proj = _project(project)
    if isinstance(proj, str):
        return proj
    manifest = _manifest_or_error(proj)
    if isinstance(manifest, str):
        return manifest
    rows = []
    sections = {"nodes": None, "sources": "source", "exposures": "exposure", "macros": "macro"}
    for section, forced_type in sections.items():
        for uid, node in manifest.get(section, {}).items():
            rtype = forced_type or node.get("resource_type")
            if rtype == "test":
                continue
            if resource_type and rtype != resource_type:
                continue
            if pattern and pattern not in node.get("name", ""):
                continue
            if stale_meta and is_stale(node) is not True:
                continue
            desc = (node.get("description") or "").strip().splitlines()
            rows.append(
                {"name": node.get("name"), "type": rtype, "description": desc[0] if desc else "",
                 "has_meta": bool(claude_meta(node))}
            )
    return json.dumps(rows)


@mcp.tool(
    annotations={"title": "Get node documentation", "readOnlyHint": True, "idempotentHint": True},
    description=(
        "Tiered documentation for one dbt node (model, source, seed, snapshot, "
        "exposure, macro). detail='summary' (default): derived facts (keys, joins, "
        "enums from tests) plus the meta.claude block. detail='columns': adds "
        "per-column docs; pass columns=[...] to restrict. detail='full': the whole "
        "property entry (expensive — prefer summary/columns). Returns documentation, "
        "not warehouse rows — use dbt_inspect with subcommand='show' for data.\n\n"
        "meta.claude field semantics:\n" + _CONTRACT
    ),
)
def get_node(
    name: str,
    detail: Literal["summary", "columns", "full"] = "summary",
    columns: list[str] | None = None,
    project: str | None = None,
) -> str:
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    _, manifest, uid, node = located
    checksum = node.get("checksum", {}).get("checksum", "")
    rendered = json.loads(render_node(manifest, uid, detail, columns))
    if checksum:
        rendered["checksum_prefix"] = checksum[:12]
    return json.dumps(rendered)


@mcp.tool(
    annotations={"title": "Node lineage", "readOnlyHint": True, "idempotentHint": True}
)
def lineage(
    name: str,
    direction: Literal["upstream", "downstream"] = "upstream",
    depth: int = 1,
    project: str | None = None,
) -> str:
    """Upstream or downstream node ids for a node, depth-capped (max 5).
    Names only — use get_node on results for detail."""
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    _, manifest, uid, _ = located
    return json.dumps(_lineage(manifest, uid, direction, min(depth, 5)))


@mcp.tool(
    annotations={"title": "Resolve ref/source", "readOnlyHint": True, "idempotentHint": True}
)
def resolve(ref_or_source: str, project: str | None = None) -> str:
    """Resolve a ref('x') / source('a','b') string or bare name to its node:
    unique_id, file path, relation name."""
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    manifest = _manifest_or_error(proj)
    if isinstance(manifest, str):
        return manifest
    found = resolve_ref(manifest, ref_or_source)
    if not found:
        return f"error: could not resolve {ref_or_source!r}"
    uid, node = found
    return json.dumps(
        {"unique_id": uid, "path": node.get("original_file_path"),
         "relation": node.get("relation_name")}
    )


@mcp.tool(
    annotations={"title": "dbt inspect (read-only)", "readOnlyHint": True}
)
def dbt_inspect(
    subcommand: Literal["parse", "compile", "show", "ls"],
    select: str | None = None,
    args: list[str] | None = None,
    limit: int = 20,
    project: str | None = None,
) -> str:
    """Run a no-side-effect dbt subcommand: parse, compile, show (rows, capped),
    ls. Never mutates the warehouse — use dbt_build for build/run/test."""
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    return json.dumps(run_dbt(proj, subcommand, INSPECT_SUBCOMMANDS, select, args, min(limit, 20)))


@mcp.tool(annotations={"title": "dbt build (mutates warehouse)"})
def dbt_build(
    subcommand: Literal["build", "run", "test", "snapshot", "seed"],
    select: str | None = None,
    args: list[str] | None = None,
    project: str | None = None,
) -> str:
    """Run a warehouse-mutating dbt subcommand: build, run, test, snapshot,
    seed. Returns pass/fail counts and first error per failing node.
    Read-only inspection belongs in dbt_inspect."""
    proj = _project(project)
    if isinstance(proj, str):
        return proj
    return json.dumps(run_dbt(proj, subcommand, BUILD_SUBCOMMANDS, select, args))


@mcp.tool(
    annotations={"title": "Write property YAML entry", "destructiveHint": True}
)
def write_yaml(
    resource_type: Literal["model", "seed", "snapshot", "source", "exposure"],
    name: str,
    entry: dict,
    project: str | None = None,
) -> str:
    """Create or FULLY REPLACE a node's property YAML entry. Replacement is
    also how fields are removed. For partial updates use edit_yaml. The node
    must exist in the manifest (a new model's SQL file is picked up by the
    staleness auto-parse). Returns a unified diff — review it."""
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    proj, manifest, _, _ = located
    return write_entry(proj.path, manifest, resource_type, name, entry) or "no change"


@mcp.tool(annotations={"title": "Edit property YAML entry"})
def edit_yaml(
    resource_type: Literal["model", "seed", "snapshot", "source", "exposure"],
    name: str,
    fields: dict,
    project: str | None = None,
) -> str:
    """Merge a structured patch into an EXISTING property entry (columns merge
    by name). Errors if the node has no entry — use write_yaml to create one.
    Returns a unified diff — review it."""
    located = _locate(name, project)
    if isinstance(located, str):
        return located
    proj, manifest, _, _ = located
    try:
        return edit_entry(proj.path, manifest, resource_type, name, fields) or "no change"
    except NoEntryError as exc:
        return f"error: {exc}"


def main() -> None:
    reset(Path(os.environ.get("DBT_AGENT_TOOLS_ROOT", ".")).resolve())
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_server.py -v`, then the full suite
`uv run pytest -v`.
Expected: all pass. (fastmcp v3 API drift: if `@mcp.tool` rejects the
`annotations` or `description` kwarg shapes, check
`uv run python -c "import fastmcp; print(fastmcp.__version__)"` and consult
the fastmcp docs for the current kwarg names — the test pins the required
behavior, not the API.)

- [ ] **Step 5: Commit**

```bash
git add src/dbt_agent_tools/server.py tests/test_server.py
git commit -m "feat: assemble MCP server with annotated tool surface"
```

---

### Task 11: Plugin packaging and README

**Files:**

- Create: `.claude-plugin/plugin.json`
- Create: `.mcp.json`
- Create: `README.md`
- Create: `.gitignore`

**Interfaces:**

- Consumes: console script `dbt-agent-tools` (Task 10); skill dir (Task 9).
- Produces: installable Claude Code plugin; marketplace entry snippet for
  `cbini/dotclaude` (hand to the user — separate repo).

- [ ] **Step 1: Write plugin manifest and MCP config**

`.claude-plugin/plugin.json`:

```json
{
  "name": "dbt-agent-tools",
  "description": "Progressive-disclosure dbt docs, guarded CLI exec, and structured YAML authoring for agents",
  "version": "0.1.0",
  "author": { "name": "Charlie Bini" }
}
```

`.mcp.json`:

```json
{
  "mcpServers": {
    "dbt-agent-tools": {
      "command": "uv",
      "args": ["run", "--project", "${CLAUDE_PLUGIN_ROOT}", "dbt-agent-tools"]
    }
  }
}
```

`.gitignore`:

```text
__pycache__/
*.egg-info/
.venv/
target/
*.duckdb
```

- [ ] **Step 2: Write README**

`README.md` — cover, briefly (link the spec for depth):

- What it is (the one-line pitch: a structured, queryable CLAUDE.md for dbt).
- Install: `claude plugin marketplace add cbini/dotclaude` +
  `claude plugin install dbt-agent-tools@dotclaude`; manual `.mcp.json`
  alternative for non-plugin use.
- Configuration: `DBT_AGENT_TOOLS_ROOT` (workspace root, default cwd),
  `DBT_AGENT_TOOLS_DBT_CMD` (default `dbt`; monorepos set `uv run dbt`).
- Tool table: the 9 tools, one line each.
- The meta.claude contract: link to
  `skills/authoring/references/meta-claude-contract.md`.
- Dev: `uv sync && uv run pytest`.

- [ ] **Step 3: Smoke-test the entry point**

Run: `cd /workspaces/dbt-agent-tools && timeout 5 uv run dbt-agent-tools <<< '' ; echo "exit: $?"`
Expected: server starts on stdio and exits on closed stdin without traceback
(exit 0 or 124). Fix `main()` if it stack-traces.

- [ ] **Step 4: Full suite, commit, push**

Run: `uv run pytest -v` — all pass.

```bash
git add .claude-plugin .mcp.json README.md .gitignore
git commit -m "feat: package as Claude Code plugin with README"
git push
```

- [ ] **Step 5: Hand the marketplace entry to the user**

Give the user this snippet to add to `cbini/dotclaude`
`.claude-plugin/marketplace.json` `plugins` array (their repo, their commit):

```json
{
  "name": "dbt-agent-tools",
  "source": { "source": "github", "repo": "cbini/dbt-agent-tools" },
  "description": "Progressive-disclosure dbt docs, guarded CLI exec, structured YAML authoring"
}
```

---

## Deferred (explicitly out of this plan)

- Skill-creator eval loop for the authoring skill (spec's authoring-skill
  evals beyond the trigger set) — run interactively after v0.1 ships, per
  skill-creator's iteration workflow.
- Real-world validation against the teamster monorepo — manual spot-check
  after Task 11: add the server to teamster's `.mcp.json` with
  `DBT_AGENT_TOOLS_DBT_CMD="uv run dbt"` and `DBT_AGENT_TOOLS_ROOT=src/dbt`,
  then `get_node` a few kipptaf models.
- `write_yaml`/`edit_yaml` support for macros and singular tests (property
  YAML for those is rare; read side already covers them).
- Property-entry-based fingerprints for sources/exposures (spec §contract):
  `is_stale` returns `None` for nodes without a file checksum in v0.1; add
  entry-hash fingerprints when source/exposure meta.claude sees real use.
