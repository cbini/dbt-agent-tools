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
