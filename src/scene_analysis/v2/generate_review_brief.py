#!/usr/bin/env python3
"""
IR V2 — Generate Review Brief

Combines _manifest.json, _extraction.json, and _condition_path.json
into a single readable markdown brief per pattern. Designed so a human
expert can read ONE file and understand the pattern's implementation.

Includes a checklist for the review process and instructions for
what to do after review is complete.

Input:
  data/processed/scene_analysis/<pattern>_manifest.json
  data/processed/scene_analysis/<pattern>_extraction.json
  data/processed/scene_analysis/<pattern>_condition_path.json

Output:
  data/processed/scene_analysis/<pattern>_review_brief.md

Usage:
    uv run python src/scene_analysis/v2/generate_review_brief.py
    uv run python src/scene_analysis/v2/generate_review_brief.py 1_Ownership
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCENE_ANALYSIS_DIR = ROOT / "data" / "processed" / "scene_analysis"

THREE_PATTERNS = ["1_Ownership", "11_Delivery", "14_Alignment_new"]

ALL_PATTERNS = [
    "1_Ownership", "2_Collection", "3_Eliminate", "4_Capture",
    "5_Overcome", "6_Evade", "7_Stealth", "8_Herd_Attract",
    "9_Conceal", "10_Rescue", "11_Delivery", "12_Guard",
    "13_Race", "14_Alignment_new", "15_Configuration", "16_Traverse",
    "17_Survive", "18_Connection_Line", "19_Exploration",
    "20_Reconnaissance", "21_Contact", "22_Enclosure",
    "23_GainCompetence", "24_GainInformation",
    "25_LastManStanding_Escaping", "26_KingoftheHill",
]


def generate_brief(pattern: str) -> str | None:
    manifest_path = SCENE_ANALYSIS_DIR / f"{pattern}_manifest.json"
    extraction_path = SCENE_ANALYSIS_DIR / f"{pattern}_extraction.json"
    cpath_path = SCENE_ANALYSIS_DIR / f"{pattern}_condition_path.json"

    if not all(p.exists() for p in [manifest_path, extraction_path, cpath_path]):
        return None

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    with open(extraction_path, encoding="utf-8") as f:
        extraction = json.load(f)
    with open(cpath_path, encoding="utf-8") as f:
        cpath = json.load(f)

    scripts = manifest["scripts"]
    demands = manifest["demands"]
    condition_path = cpath["condition_path"]

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────
    lines.append(f"# Review Brief: {pattern}")
    lines.append("")
    lines.append("This brief combines the automated pipeline outputs into a single")
    lines.append("readable document. Review this file, complete the checklist at the")
    lines.append("bottom, then proceed to IR authoring.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 1. Win/Lose Condition Path ────────────────────────────────────
    lines.append("## 1. Win/Lose Condition Path")
    lines.append("")
    lines.append("The automated call chain from gameplay event to GameManager.GameWin/GameLose,")
    lines.append("with source file and line number evidence.")
    lines.append("")

    for path_type in ["win", "lose"]:
        steps = condition_path[path_type]
        if not steps:
            lines.append(f"**{path_type.upper()} path:** (none detected)")
            lines.append("")
            continue

        lines.append(f"**{path_type.upper()} path** ({len(steps)} steps):")
        lines.append("")
        for i, step in enumerate(steps, 1):
            lines.append(f"**Step {i}** — `{step['actor_class']}.{step['event']}()`")
            if step["conditions"]:
                for cond in step["conditions"]:
                    lines.append(f"- Condition: `{cond}`")
            lines.append(f"- Effect: `{step['effect']}`")
            lines.append(f"- Evidence: `{step['evidence']}`")
            # Include the full method body for review context
            body = step.get("method_body")
            if body:
                body_stripped = body.strip()
                if body_stripped:
                    lines.append("")
                    lines.append(f"<details><summary>Full method body</summary>")
                    lines.append("")
                    lines.append(f"```csharp")
                    lines.append(f"// {step['actor_class']}.{step['event']}()")
                    lines.append(body_stripped)
                    lines.append(f"```")
                    lines.append("")
                    lines.append(f"</details>")
            lines.append("")

    # ── 2. Inspector Values (for condition path classes) ──────────────
    lines.append("## 2. Key Inspector Values")
    lines.append("")
    lines.append("Inspector-configured fields for classes involved in the condition path.")
    lines.append("Use these to fill in concrete numbers referenced in the conditions above.")
    lines.append("")

    cpath_classes = set(demands.get("condition_path_classes", []))
    inspector = extraction.get("inspector_values", {})

    # Show condition path classes first, then others
    shown: set[str] = set()
    for cls in sorted(cpath_classes):
        if cls in inspector:
            info = inspector[cls]
            lines.append(f"**{cls}** (GO: {info['go_name']})")
            lines.append("")
            for field, value in info["fields"].items():
                lines.append(f"- `{field}` = `{json.dumps(value)}`")
            lines.append("")
            shown.add(cls)

    # Other inspector values
    others = {cls: info for cls, info in inspector.items() if cls not in shown}
    if others:
        lines.append("### Other Scripts with Inspector Values")
        lines.append("")
        for cls, info in sorted(others.items()):
            lines.append(f"**{cls}** (GO: {info['go_name']})")
            lines.append("")
            for field, value in info["fields"].items():
                lines.append(f"- `{field}` = `{json.dumps(value)}`")
            lines.append("")

    # ── 3. Component Data ─────────────────────────────────────────────
    comp_data = extraction.get("component_data", {})
    has_physics = any(
        c.get("colliders") or c.get("rigidbodies")
        for c in comp_data.values()
    )
    if has_physics:
        lines.append("## 3. Physics Components")
        lines.append("")
        lines.append("Collider and Rigidbody configuration for scripts that use physics callbacks.")
        lines.append("")

        for cls, info in sorted(comp_data.items()):
            if not info.get("colliders") and not info.get("rigidbodies"):
                continue
            origin_label = f"[{info['origin']}]" if info.get("origin") else ""
            lines.append(f"**{cls}** {origin_label} (GO: {info.get('go_name', '?')})")
            if info.get("implied_by"):
                lines.append(f"- Implied by: {', '.join(info['implied_by'])}")
            for col in info.get("colliders", []):
                trigger = "trigger" if col.get("m_IsTrigger") else "solid"
                size = col.get("m_Size", {})
                size_str = f"{size.get('x', '?')}×{size.get('y', '?')}" if size else "?"
                lines.append(f"- Collider: `{col['type']}` ({trigger}, size {size_str})")
            for rb in info.get("rigidbodies", []):
                body_types = {0: "Dynamic", 1: "Kinematic", 2: "Static"}
                bt = body_types.get(rb.get("m_BodyType"), "?")
                gs = rb.get("m_GravityScale", "?")
                lines.append(f"- Rigidbody: `{rb['type']}` (bodyType={bt}, gravityScale={gs})")
            lines.append("")

    # ── 4. Prefab References ──────────────────────────────────────────
    prefab_refs = extraction.get("prefab_refs", {})
    if prefab_refs:
        lines.append("## 4. Prefab References")
        lines.append("")
        for cls, refs in sorted(prefab_refs.items()):
            for ref in refs:
                lines.append(f"- `{cls}.{ref['field']}` → prefab **{ref['prefab_name']}**")
                if ref.get("prefab_scripts"):
                    lines.append(f"  - Scripts inside: {', '.join(ref['prefab_scripts'])}")
        lines.append("")

    # ── 5. Tags ───────────────────────────────────────────────────────
    tags = extraction.get("tags_found", {})
    if tags:
        lines.append("## 5. Tags")
        lines.append("")
        for tag, gos in sorted(tags.items()):
            go_names = ", ".join(g["go_name"] for g in gos)
            lines.append(f"- `{tag}` → {go_names}")
        lines.append("")

    # ── 6. Script Inventory ───────────────────────────────────────────
    lines.append("## 6. Script Inventory")
    lines.append("")
    lines.append("| Class | Origin | GO Name | In Condition Path | Source |")
    lines.append("|-------|--------|---------|:-----------------:|--------|")
    for cls, sinfo in sorted(scripts.items()):
        origin = sinfo.get("origin", "scene")
        go_name = sinfo.get("go_name", "")
        if origin == "prefab":
            go_name = f"(prefab) {sinfo.get('prefab_name', '')}"
        in_cpath = "yes" if cls in cpath_classes else ""
        source = sinfo.get("source_file", "")
        # Shorten source path for readability
        short_source = source.replace("data/raw/unity/PatternsUnityCode/", "")
        lines.append(f"| {cls} | {origin} | {go_name} | {in_cpath} | `{short_source}` |")
    lines.append("")

    # ── Review Checklist ──────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## Review Checklist")
    lines.append("")
    lines.append("Complete each item. Mark `[x]` when done, or note issues.")
    lines.append("")
    lines.append("### 0. Play First")
    lines.append("")
    lines.append("- [ ] I played this pattern in the Unity Editor. I won (and tried to lose).")
    lines.append("")
    lines.append("### A. Does the win/lose path match my experience? (→ Section 1 + 2)")
    lines.append("")
    lines.append("- [ ] **A1.** The win path in Section 1 matches how I won the game.")
    lines.append("- [ ] **A2.** The lose path (or \"none detected\") matches my experience.")
    lines.append("- [ ] **A3.** I opened `GameManager.cs` and searched for `GameWin` / `GameLose`.")
    lines.append("      No other script calls them besides the ones listed in Section 1.")
    lines.append("- [ ] **A4.** The numbers in Section 2 match the game feel.")
    lines.append("      (e.g., if Section 2 says `goalCount=8`, I did touch roughly 8 things to win.)")
    lines.append("")
    lines.append("### B. Do I know what every script does? (→ Section 6)")
    lines.append("")
    lines.append("Look at the Script Inventory table (Section 6). For each script:")
    lines.append("")
    lines.append("- [ ] **B1.** I can describe in one sentence what each script does.")
    lines.append("      (If not, expand the method bodies in Section 1, or open the .cs file.)")
    lines.append("- [ ] **B2.** I know which scripts are gameplay logic and which are UI/infrastructure.")
    lines.append("      (Hint: scripts on GOs named Canvas, Text, Panel are typically UI.)")
    lines.append("")
    lines.append("### C. Does the physics setup make sense? (→ Section 3)")
    lines.append("")
    lines.append("- [ ] **C1.** If the win path involves a collision/trigger event,")
    lines.append("      Section 3 shows a collider marked `trigger` on the relevant object.")
    lines.append("- [ ] **C2.** The player object has a Rigidbody2D listed in Section 3.")
    lines.append("")
    lines.append("### D. Write the domain description (you fill in)")
    lines.append("")
    lines.append("- [ ] **D1.** One sentence: what does the player do to win?")
    lines.append("      Example: \"Player touches all 8 objects to change their color.\"")
    lines.append("      Your answer: ___")
    lines.append("- [ ] **D2.** One sentence: what does the player do to lose? (or \"no lose condition\")")
    lines.append("      Your answer: ___")
    lines.append("- [ ] **D3.** Any non-obvious implementation details worth noting?")
    lines.append("      (e.g., objects are spawned at start, singleton pattern, etc.)")
    lines.append("      Your answer: ___")
    lines.append("")

    # ── After Review ──────────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## After Review: Author the IR")
    lines.append("")
    lines.append("Once all checklist items are complete, author the IR JSON file:")
    lines.append("")
    lines.append(f"**Output:** `data/processed/scene_analysis/{pattern}_ir_v2.json`")
    lines.append("")
    lines.append("Use the following structure (adapt fields as needed):")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append(f'  "pattern": "{pattern}",')
    lines.append('  "version": "v2",')
    lines.append('  "win_condition": {')
    lines.append('    "description": "<D1: one-sentence domain description>",')
    lines.append('    "path": <copy from Section 1 win path, or edit as needed>')
    lines.append('  },')
    lines.append('  "lose_condition": {')
    lines.append('    "description": "<or null if no lose path>",')
    lines.append('    "path": <copy from Section 1 lose path>')
    lines.append('  },')
    lines.append('  "entities": [')
    lines.append('    {')
    lines.append('      "name": "<from B1>",')
    lines.append('      "role": "<from B2>",')
    lines.append('      "scripts": ["<class_name>", ...],')
    lines.append('      "inspector_values": { "<field>": "<value>", ... }')
    lines.append('    }')
    lines.append('  ],')
    lines.append('  "excluded_scripts": ["<from B3>"],')
    lines.append('  "meta": {')
    lines.append('    "coding_notes": "<D2>",')
    lines.append('    "reviewer": "<your name>",')
    lines.append('    "review_date": "<date>"')
    lines.append('  }')
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("The IR should be self-contained: a reader should be able to understand")
    lines.append("the pattern's implementation without opening any other file.")

    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if not args:
        patterns = THREE_PATTERNS
    elif args[0] == "--all":
        patterns = ALL_PATTERNS
    else:
        patterns = args

    ok = 0
    for pattern in patterns:
        brief = generate_brief(pattern)
        if brief is None:
            print(f"  SKIP  {pattern} (missing pipeline outputs)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_review_brief.md"
        out_path.write_text(brief, encoding="utf-8")
        print(f"  {pattern} → {out_path.name}")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} briefs generated.")


if __name__ == "__main__":
    main()
