#!/usr/bin/env python3
"""
IR V2 — Generate IR (behavior-only IR, no scene representation)

Merges pipeline outputs into a single self-contained IR JSON:
  - Pass 1 manifest: script analysis, demands
  - Pass 2 extraction: inspector values, physics components
  - Pass 3 condition path: win/lose chains with evidence

The result is a behavior-only IR — no scene representation.
V2 differs from V4 by omitting the `scene` section.

Input:
  data/processed/scene_analysis/<pattern>_manifest.json
  data/processed/scene_analysis/<pattern>_extraction.json
  data/processed/scene_analysis/<pattern>_condition_path.json

Output:
  data/ir_v2/<pattern>_ir_v2_full.json

Usage:
    uv run python src/scene_analysis/v2/generate_ir_v2.py
    uv run python src/scene_analysis/v2/generate_ir_v2.py 1_Ownership
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCENE_ANALYSIS_DIR = ROOT / "data" / "processed" / "scene_analysis"
IR_V2_DIR          = ROOT / "data" / "ir_v2"

sys.path.insert(0, str(ROOT / "src"))
from scene_analysis.v2.trace_condition_path import analyze_cs_file

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
    path = ROOT / source_file
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(re.findall(
        r'(?:public|(?:\[SerializeField\]\s*(?:private|protected)))\s+bool\s+(\w+)', text
    ))


def _fix_bools(fields: dict, bool_names: set[str]) -> dict:
    return {
        k: (bool(v) if k in bool_names and isinstance(v, int) else v)
        for k, v in fields.items()
    }


# UI GO names — scripts on these GOs are UI boilerplate, not gameplay logic.
# Their method bodies reference external UI packages (TextMeshPro, CanvasScaler)
# that are not available in a clean Unity project.
UI_SCRIPT_GO_NAMES = {"Canvas", "Text (Legacy)", "EventSystem"}


def _sanitize_ui_methods(cls: str, methods: dict[str, str]) -> dict[str, str]:
    """
    Remove UI references from all method bodies.

    1. GameWin/GameLose: replace entirely with Debug.Log + Time.timeScale = 0
    2. All other methods: remove lines that reference Menu/UI components

    This is a documented lossy operation: we lose UI presentation details
    but keep gameplay state changes.
    """
    UI_REFS = ["m_Menu", "Menu", "winPanel", "losePanel", "Canvas", "Panel",
               "GetComponentInChildren<Menu>"]

    result = dict(methods)

    # Replace GameWin/GameLose entirely
    for method_name in ["GameWin", "GameLose"]:
        if method_name not in result:
            continue
        body = result[method_name]
        if any(ui_ref in body for ui_ref in UI_REFS):
            label = "Win" if method_name == "GameWin" else "Lose"
            result[method_name] = (
                f'Debug.Log("You {label}!");\n'
                f'        Time.timeScale = 0;'
            )

    # Strip UI-referencing lines from all other methods
    for method_name in list(result.keys()):
        if method_name in ["GameWin", "GameLose"]:
            continue
        body = result[method_name]
        if any(ui_ref in body for ui_ref in UI_REFS):
            cleaned_lines = []
            for line in body.split("\n"):
                if not any(ui_ref in line for ui_ref in UI_REFS):
                    cleaned_lines.append(line)
            result[method_name] = "\n".join(cleaned_lines)

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

    # ── behavior layer (from Pass 1-3) ────────────────────────────────
    behavior: dict[str, dict] = {}
    for cls, sinfo in scripts_info.items():
        # Skip UI-only scripts — their GO names indicate they are UI boilerplate.
        # Their behavior (showing win/lose panels) is replaced by Debug.Log in
        # GameManager.GameWin/GameLose. This is a documented lossy decision.
        go_name = sinfo.get("go_name", "")
        if go_name in UI_SCRIPT_GO_NAMES:
            continue

        entry: dict = {
            "origin":           sinfo.get("origin", "scene"),
            "go_name":          sinfo.get("go_name", ""),
            "callbacks":        sinfo.get("callbacks", []),
            "singleton_calls":  sinfo.get("singleton_calls", []),
            "singleton_writes": sinfo.get("singleton_writes", []),
        }
        if sinfo.get("origin") == "prefab":
            entry["prefab_name"] = sinfo.get("prefab_name", "")

        # Inspector values with bool fix
        insp = extraction.get("inspector_values", {}).get(cls)
        if insp:
            entry["go_name"] = insp.get("go_name", entry["go_name"])
            bool_fields = _get_bool_fields(sinfo.get("source_file", ""))
            entry["inspector_fields"] = _fix_bools(insp.get("fields", {}), bool_fields)

        # All method bodies from .cs source
        source_file = sinfo.get("source_file", "")
        if source_file:
            cs_path = ROOT / source_file
            if cs_path.exists():
                analysis = analyze_cs_file(cs_path)
                methods: dict[str, str] = {}
                for scope in [analysis.get("callbacks", {}), analysis.get("methods", {})]:
                    for method_name, mdata in scope.items():
                        body = mdata.get("body", "").strip()
                        if body:
                            methods[method_name] = body
                if methods:
                    entry["methods"] = _sanitize_ui_methods(cls, methods)

        behavior[cls] = entry

    # ── condition path (from Pass 3) ──────────────────────────────────
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
            if step.get("method_body"):
                clean_step["method_body"] = step["method_body"].strip()
            clean_steps.append(clean_step)
        condition_path[path_type] = clean_steps

    # ── prefab refs ───────────────────────────────────────────────────
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

    return {
        "pattern":        pattern,
        "version":        "v2",
        "behavior":       behavior,
        "condition_path": condition_path,
        "prefab_refs":    prefab_refs,
        "tags":           tags,
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

    IR_V2_DIR.mkdir(parents=True, exist_ok=True)

    ok = 0
    for pattern in patterns:
        ir = generate_ir(pattern)
        if ir is None:
            print(f"  SKIP  {pattern} (missing pipeline outputs)")
            continue

        out_path = IR_V2_DIR / f"{pattern}_ir_v2_full.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(ir, f, indent=2, ensure_ascii=False)

        n_behavior = len(ir["behavior"])
        n_win      = len(ir["condition_path"]["win"])
        n_lose     = len(ir["condition_path"]["lose"])

        print(f"  {pattern}: behavior={n_behavior} scripts, "
              f"win={n_win} lose={n_lose}")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} IR v2 files generated.")


if __name__ == "__main__":
    main()
