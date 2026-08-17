from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_packaged_contract_matches_canonical() -> None:
    canonical = ROOT / "skills/authoring/references/meta-claude-contract.md"
    packaged = ROOT / "src/dbt_agent_tools/_contract.md"
    assert packaged.read_text() == canonical.read_text(), (
        "run: uv run python scripts/sync_contract.py"
    )
