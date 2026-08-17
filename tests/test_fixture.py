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
