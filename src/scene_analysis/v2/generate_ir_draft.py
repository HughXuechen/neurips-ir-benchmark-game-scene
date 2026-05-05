#!/usr/bin/env python3
"""
IR V2 — Generate IR Draft (Full level)

Merges _manifest.json, _extraction.json, and _condition_path.json into
a single self-contained IR JSON per pattern. This is the "Full" level —
all concrete values included. Structure-only and Abstract levels can be
derived from this by stripping values.

The output is a draft: human adds domain descriptions (D1–D3 from the
review checklist), then it becomes the final IR.

Input:
  data/processed/scene_analysis/<pattern>_manifest.json
  data/processed/scene_analysis/<pattern>_extraction.json
  data/processed/scene_analysis/<pattern>_condition_path.json

Output:
  data/processed/scene_analysis/<pattern>_ir_v2_full.json

Usage:
    uv run python src/scene_analysis/v2/generate_ir_draft.py
    uv run python src/scene_analysis/v2/generate_ir_draft.py 1_Ownership
"""

from __future__ import annotations

import json
import re
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


def _get_bool_fields(source_file: str) -> set[str]:
    """Read a .cs file and return the names of all public bool fields."""
    path = ROOT / source_file
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r'(?:public|(?:\[SerializeField\]\s*(?:private|protected)))\s+bool\s+(\w+)', text))


def _fix_bool_fields(fields: dict, bool_names: set[str]) -> dict:
    """Convert 0/1 int values to true/false for declared bool fields."""
    result = {}
    for k, v in fields.items():
        if k in bool_names and isinstance(v, int):
            result[k] = bool(v)
        else:
            result[k] = v
    return result


def generate_ir(pattern: str) -> dict | None:
    manifest_path   = SCENE_ANALYSIS_DIR / f"{pattern}_manifest.json"
    extraction_path = SCENE_ANALYSIS_DIR / f"{pattern}_extraction.json"
    cpath_path      = SCENE_ANALYSIS_DIR / f"{pattern}_condition_path.json"

    if not all(p.exists() for p in [manifest_path, extraction_path, cpath_path]):
        return None

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    with open(extraction_path, encoding="utf-8") as f:
        extraction = json.load(f)
    with open(cpath_path, encoding="utf-8") as f:
        cpath = json.load(f)

    scripts_info = manifest["scripts"]
    demands      = manifest["demands"]

    # ── scripts: per-class summary ────────────────────────────────────
    scripts: dict[str, dict] = {}
    for cls, sinfo in scripts_info.items():
        entry: dict = {
            "origin":     sinfo.get("origin", "scene"),
            "go_name":    sinfo.get("go_name", ""),
            "callbacks":  sinfo.get("callbacks", []),
            "singleton_calls":  sinfo.get("singleton_calls", []),
            "singleton_writes": sinfo.get("singleton_writes", []),
        }
        if sinfo.get("origin") == "prefab":
            entry["prefab_name"] = sinfo.get("prefab_name", "")

        # Merge inspector values from extraction, fixing bool fields
        insp = extraction.get("inspector_values", {}).get(cls)
        if insp:
            entry["go_name"] = insp.get("go_name", entry["go_name"])
            bool_fields = _get_bool_fields(sinfo.get("source_file", ""))
            entry["inspector_fields"] = _fix_bool_fields(insp.get("fields", {}), bool_fields)

        # Merge physics components from extraction
        comp = extraction.get("component_data", {}).get(cls)
        if comp:
            if comp.get("colliders"):
                entry["colliders"] = comp["colliders"]
            if comp.get("rigidbodies"):
                entry["rigidbodies"] = comp["rigidbodies"]
            if comp.get("implied_by"):
                entry["implied_by"] = comp["implied_by"]

        scripts[cls] = entry

    # ── prefab_refs ───────────────────────────────────────────────────
    prefab_refs: list[dict] = []
    for cls, refs in extraction.get("prefab_refs", {}).items():
        for ref in refs:
            prefab_refs.append({
                "from_class":     cls,
                "field":          ref["field"],
                "prefab_name":    ref["prefab_name"],
                "prefab_scripts": ref.get("prefab_scripts", []),
            })

    # ── tags ──────────────────────────────────────────────────────────
    tags: dict[str, str] = {}
    for tag, gos in extraction.get("tags_found", {}).items():
        tags[tag] = gos[0]["go_name"] if gos else ""

    # ── condition path (strip method_body for cleanliness) ────────────
    condition_path: dict[str, list[dict]] = {}
    for path_type in ["win", "lose"]:
        steps = cpath.get("condition_path", {}).get(path_type, [])
        clean_steps = []
        for step in steps:
            clean_step = {
                "step":        step["step"],
                "actor_class": step["actor_class"],
                "event":       step["event"],
                "conditions":  step["conditions"],
                "effect":      step["effect"],
                "evidence":    step["evidence"],
            }
            # Keep method_body — it's useful for LLM context
            if step.get("method_body"):
                clean_step["method_body"] = step["method_body"].strip()
            clean_steps.append(clean_step)
        condition_path[path_type] = clean_steps

    return {
        "pattern":        pattern,
        "version":        "v2_full",
        "scripts":        scripts,
        "prefab_refs":    prefab_refs,
        "tags":           tags,
        "condition_path": condition_path,
        "meta": {
            "win_description":  None,
            "lose_description": None,
            "coding_notes":     None,
            "reviewer":         None,
            "review_date":      None,
        },
    }


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
        ir = generate_ir(pattern)
        if ir is None:
            print(f"  SKIP  {pattern} (missing pipeline outputs)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_ir_v2_full.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(ir, f, indent=2, ensure_ascii=False)

        n_scripts = len(ir["scripts"])
        n_win     = len(ir["condition_path"]["win"])
        n_lose    = len(ir["condition_path"]["lose"])
        print(f"  {pattern}: {n_scripts} scripts, win={n_win} lose={n_lose}")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} IR drafts generated.")


if __name__ == "__main__":
    main()
