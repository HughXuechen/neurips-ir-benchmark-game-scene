"""
Fill the coder_no_schema prompt template for all 26 goal patterns.

Reads:
  data/raw/goal_patterns/<Name>.md   — pattern description
  src/prompts/coder_no_schema.txt    — template

Writes (per pattern, under results/prompts/<pattern_id>/):
  coder_no_schema.txt

The V2/V4 IR-conditioned prompts (coder_with_v2_ir / coder_with_v4_ir)
include IR content generated separately and are not produced here.

Usage:
  uv run python src/prompts/generate_prompts.py
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Mapping: .md filename stem → canonical pattern_id
# The pattern_id matches the keys used in data/processed/scene_analysis/
# ---------------------------------------------------------------------------
PATTERN_MAP: dict[str, str] = {
    "Alignment":        "14_Alignment_new",
    "Capture":          "4_Capture",
    "Collection":       "2_Collection",
    "Conceal":          "9_Conceal",
    "Configuration":    "15_Configuration",
    "Connection":       "18_Connection_Line",
    "Contact":          "21_Contact",
    "Delivery":         "11_Delivery",
    "Eliminate":        "3_Eliminate",
    "Enclosure":        "22_Enclosure",
    "Evade":            "6_Evade",
    "Exploration":      "19_Exploration",
    "GainCompetence":   "23_GainCompetence",
    "GainInformation":  "24_GainInformation",
    "GainOwnership":    "1_Ownership",
    "Guard":            "12_Guard",
    "Herd":             "8_Herd_Attract",
    "KingoftheHill":    "26_KingoftheHill",
    "LastManStanding":  "25_LastManStanding_Escaping",
    "Overcome":         "5_Overcome",
    "Race":             "13_Race",
    "Reconnaissance":   "20_Reconnaissance",
    "Rescue":           "10_Rescue",
    "Stealth":          "7_Stealth",
    "Survive":          "17_Survive",
    "Traverse":         "16_Traverse",
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT    = Path(__file__).resolve().parents[2]
PATTERNS_DIR = REPO_ROOT / "data" / "raw" / "goal_patterns"
TEMPLATES_DIR = REPO_ROOT / "src" / "prompts"
RESULTS_ROOT = Path(os.getenv("RESULTS_ROOT", str(REPO_ROOT / "results")))
OUT_ROOT     = RESULTS_ROOT / "prompts"

TEMPLATES = {
    "coder_no_schema": TEMPLATES_DIR / "coder_no_schema.txt",
}


def fill_template(template: str, pattern_id: str, pattern_md: str) -> str:
    return (
        template
        .replace("<PATTERN_ID>", pattern_id)
        .replace("<PATTERN_MD>", pattern_md)
    )


def main() -> None:
    # Load templates once
    templates = {name: path.read_text(encoding="utf-8") for name, path in TEMPLATES.items()}

    generated = 0
    skipped = 0

    for md_file in sorted(PATTERNS_DIR.glob("*.md")):
        stem = md_file.stem
        pattern_id = PATTERN_MAP.get(stem)
        if pattern_id is None:
            print(f"  [skip] {stem}.md — no mapping in PATTERN_MAP")
            skipped += 1
            continue

        pattern_md = md_file.read_text(encoding="utf-8")
        out_dir = OUT_ROOT / pattern_id
        out_dir.mkdir(parents=True, exist_ok=True)

        for name, template in templates.items():
            filled = fill_template(template, pattern_id, pattern_md)
            out_path = out_dir / f"{name}.txt"
            out_path.write_text(filled, encoding="utf-8")

        print(f"  [ok]   {pattern_id}")
        generated += 1

    print(f"\nDone. {generated} pattern(s) generated, {skipped} skipped.")
    print(f"Output: {OUT_ROOT}/")


if __name__ == "__main__":
    main()
