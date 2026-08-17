"""Copy the canonical contract file into the package. Run after editing it."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "skills/authoring/references/meta-claude-contract.md"
DEST = ROOT / "src/dbt_agent_tools/_contract.md"

DEST.write_text(SRC.read_text())
print(f"synced {SRC} -> {DEST}")
