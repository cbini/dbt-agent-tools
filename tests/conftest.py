from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_SRC = Path(__file__).parent / "fixture"


def run_dbt_parse(project_dir: Path) -> None:
    # dbt does not read profiles.yml from the project dir automatically;
    # it must be told where to look via DBT_PROFILES_DIR (or --profiles-dir).
    env = os.environ | {"DBT_PROFILES_DIR": "."}
    subprocess.run(
        ["dbt", "parse", "--no-use-colors"],
        cwd=project_dir,
        env=env,
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
