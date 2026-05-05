#!/usr/bin/env python3
"""
IR V2 — Prerequisite Check: Verify .cs-only logic implementation.

Scans all _parsed.json files and reports every block type found across
all patterns. Checks that no non-.cs logic mechanisms are present
(Animator, VisualScripting, PlayableDirector, StateMachineBehaviour, etc.).

This verification is a prerequisite for the V2 pipeline's core assumption:
"all gameplay logic is implemented via .cs scripts." If non-.cs logic
carriers are found, the pipeline's demand-driven approach (which enters
exclusively through .cs static analysis) would be incomplete.

Input:
  data/processed/scene_analysis/<N>_<PatternName>_parsed.json

Output:
  data/processed/scene_analysis/block_type_census.csv
  data/processed/scene_analysis/prereq_check_report.md
  stdout: PASS/FAIL verdict + exit code

Usage:
    uv run python src/scene_analysis/v2/verify_cs_only.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCENE_ANALYSIS_DIR = ROOT / "data" / "processed" / "scene_analysis"

# Block types that carry game logic through non-.cs mechanisms.
# This list is NOT guaranteed exhaustive — Unity is extensible.
# Unknown types (not in either list) are flagged for human review.
NON_CS_LOGIC_TYPES = {
    "Animator",
    "AnimatorController",
    "AnimatorOverrideController",
    "AnimatorStateMachine",
    "AnimatorState",
    "AnimatorStateTransition",
    "StateMachineBehaviour",
    "PlayableDirector",
    "VisualScripting",
    "VisualEffect",
    "SignalReceiver",
}

KNOWN_INERT_TYPES = {
    "GameObject", "Transform", "RectTransform",
    "MonoBehaviour",
    "SpriteRenderer", "CanvasRenderer", "LineRenderer",
    "TilemapRenderer", "Tilemap", "Grid",
    "Camera", "AudioListener",
    "Canvas",
    "BoxCollider2D", "CircleCollider2D", "PolygonCollider2D",
    "Rigidbody2D",
    "SpriteMask",
    "NavMeshAgent", "NavMeshSettings",
    "OcclusionCullingSettings", "RenderSettings", "LightmapSettings",
    "PrefabInstance",
}

TYPE_CATEGORIES = {
    "MonoBehaviour":          "Logic",
    "GameObject":             "Structure",
    "Transform":              "Structure",
    "RectTransform":          "Structure",
    "BoxCollider2D":          "Physics",
    "CircleCollider2D":       "Physics",
    "PolygonCollider2D":      "Physics",
    "Rigidbody2D":            "Physics",
    "SpriteRenderer":         "Rendering",
    "CanvasRenderer":         "Rendering",
    "LineRenderer":           "Rendering",
    "TilemapRenderer":        "Rendering",
    "Tilemap":                "Rendering",
    "Grid":                   "Rendering",
    "SpriteMask":             "Rendering",
    "Canvas":                 "UI",
    "Camera":                 "Infrastructure",
    "AudioListener":          "Infrastructure",
    "NavMeshAgent":           "Infrastructure",
    "NavMeshSettings":        "Infrastructure",
    "OcclusionCullingSettings": "Infrastructure",
    "RenderSettings":         "Infrastructure",
    "LightmapSettings":       "Infrastructure",
    "PrefabInstance":         "Legacy",
}


def scan_patterns() -> tuple[list[str], dict[str, dict[str, int]], Counter]:
    """Scan all _parsed.json, return (pattern_names, per_pattern_counts, totals)."""
    patterns: list[str] = []
    per_pattern: dict[str, dict[str, int]] = {}
    totals: Counter[str] = Counter()

    for f in sorted(SCENE_ANALYSIS_DIR.glob("*_parsed.json")):
        pattern = f.stem.replace("_parsed", "")
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        counts: dict[str, int] = {}
        for btype, blocks in data["blocksByType"].items():
            counts[btype] = len(blocks)
            totals[btype] += len(blocks)
        per_pattern[pattern] = counts
        patterns.append(pattern)

    return patterns, per_pattern, totals


def write_csv(
    patterns: list[str],
    per_pattern: dict[str, dict[str, int]],
    totals: Counter,
    out_path: Path,
):
    """Write block_type_census.csv: patterns × block types, with category and total."""
    sorted_types = sorted(totals.keys(), key=lambda t: (-totals[t], t))

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        header = ["pattern"] + sorted_types + ["total_blocks"]
        writer.writerow(header)

        # Category row
        cat_row = ["(category)"] + [
            TYPE_CATEGORIES.get(t, "Unknown") for t in sorted_types
        ] + [""]
        writer.writerow(cat_row)

        for pattern in patterns:
            counts = per_pattern[pattern]
            row = [pattern] + [counts.get(t, 0) for t in sorted_types]
            row.append(sum(counts.values()))
            writer.writerow(row)

        # Total row
        total_row = ["TOTAL"] + [totals[t] for t in sorted_types]
        total_row.append(sum(totals.values()))
        writer.writerow(total_row)


def write_report(
    patterns: list[str],
    per_pattern: dict[str, dict[str, int]],
    totals: Counter,
    out_path: Path,
) -> bool:
    """Write prereq_check_report.md. Returns True if PASS, False if FAIL."""
    sorted_types = sorted(totals.keys(), key=lambda t: (-totals[t], t))
    unknown_types = set(totals.keys()) - KNOWN_INERT_TYPES - NON_CS_LOGIC_TYPES

    found_non_cs: dict[str, list[str]] = {}
    for pattern in patterns:
        hits = set(per_pattern[pattern].keys()) & NON_CS_LOGIC_TYPES
        if hits:
            found_non_cs[pattern] = sorted(hits)

    passed = len(found_non_cs) == 0

    lines: list[str] = []
    lines.append("# Prerequisite Check Report: .cs-Only Logic Verification")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Patterns scanned:** {len(patterns)}")
    lines.append(f"**Block types found:** {len(totals)}")
    lines.append(f"**Total blocks:** {sum(totals.values())}")
    lines.append("")

    # Verdict
    if passed:
        lines.append("## Verdict: PASS")
        lines.append("")
        lines.append("No non-.cs logic carriers found. All gameplay logic is implemented via C# scripts.")
        lines.append("The V2 pipeline's demand-driven approach (entering through .cs static analysis) covers all gameplay logic in this dataset.")
    else:
        lines.append("## Verdict: FAIL")
        lines.append("")
        lines.append("Non-.cs logic carriers found:")
        for pattern, types in sorted(found_non_cs.items()):
            lines.append(f"- **{pattern}**: {', '.join(types)}")
        lines.append("")
        lines.append("The V2 pipeline's .cs-entry assumption does NOT hold for this dataset.")

    # Unknown types
    if unknown_types:
        lines.append("")
        lines.append("## Unknown Block Types")
        lines.append("")
        lines.append("The following types are not in the known-inert list or the non-.cs-logic list.")
        lines.append("They are not known logic carriers but should be reviewed:")
        lines.append("")
        for t in sorted(unknown_types):
            count = totals[t]
            in_patterns = [p for p in patterns if t in per_pattern[p]]
            lines.append(f"- `{t}` ({count} total, in {len(in_patterns)} patterns)")

    # Summary by category
    lines.append("")
    lines.append("## Block Type Summary by Category")
    lines.append("")

    categories_agg: dict[str, dict[str, int]] = {}
    for t in sorted_types:
        cat = TYPE_CATEGORIES.get(t, "Unknown")
        categories_agg.setdefault(cat, {})
        categories_agg[cat][t] = totals[t]

    cat_order = ["Logic", "Structure", "Physics", "Rendering", "UI", "Infrastructure", "Legacy", "Unknown"]
    for cat in cat_order:
        if cat not in categories_agg:
            continue
        types_in_cat = categories_agg[cat]
        cat_total = sum(types_in_cat.values())
        lines.append(f"**{cat}** ({cat_total} blocks)")
        lines.append("")
        lines.append("| Block Type | Count | In N Patterns |")
        lines.append("|-----------|------:|:-------------:|")
        for t, count in sorted(types_in_cat.items(), key=lambda x: -x[1]):
            n_pats = sum(1 for p in patterns if per_pattern[p].get(t, 0) > 0)
            lines.append(f"| {t} | {count} | {n_pats} |")
        lines.append("")

    # Per-pattern total
    lines.append("## Per-Pattern Block Counts")
    lines.append("")
    lines.append("| Pattern | Total Blocks | MB | GO | Physics | Rendering |")
    lines.append("|---------|------------:|---:|---:|--------:|----------:|")
    for pattern in patterns:
        c = per_pattern[pattern]
        total = sum(c.values())
        mb = c.get("MonoBehaviour", 0)
        go = c.get("GameObject", 0)
        phys = sum(c.get(t, 0) for t in ["BoxCollider2D", "CircleCollider2D", "PolygonCollider2D", "Rigidbody2D"])
        rend = sum(c.get(t, 0) for t in ["SpriteRenderer", "CanvasRenderer", "LineRenderer", "TilemapRenderer", "Tilemap", "Grid", "SpriteMask"])
        lines.append(f"| {pattern} | {total} | {mb} | {go} | {phys} | {rend} |")

    lines.append("")
    lines.append("---")
    lines.append(f"*Full per-pattern × per-type data: `block_type_census.csv`*")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return passed


def main():
    patterns, per_pattern, totals = scan_patterns()

    csv_path    = SCENE_ANALYSIS_DIR / "block_type_census.csv"
    report_path = SCENE_ANALYSIS_DIR / "prereq_check_report.md"

    write_csv(patterns, per_pattern, totals, csv_path)
    passed = write_report(patterns, per_pattern, totals, report_path)

    print(f"Scanned {len(patterns)} patterns, {len(totals)} block types, {sum(totals.values())} total blocks.\n")

    # Console summary
    for t, n in totals.most_common():
        flag = "  "
        if t in NON_CS_LOGIC_TYPES:
            flag = "!!"
        elif t not in KNOWN_INERT_TYPES:
            flag = "? "
        print(f"  {flag} {t}: {n}")

    unknown = set(totals.keys()) - KNOWN_INERT_TYPES - NON_CS_LOGIC_TYPES
    if unknown:
        print(f"\n  Unknown types (review needed): {sorted(unknown)}")

    print()
    if passed:
        print("PASS: All gameplay logic is .cs-only.")
    else:
        print("FAIL: Non-.cs logic carriers found.")

    print(f"\nOutputs:")
    print(f"  {csv_path.relative_to(ROOT)}")
    print(f"  {report_path.relative_to(ROOT)}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
