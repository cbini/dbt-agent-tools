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
