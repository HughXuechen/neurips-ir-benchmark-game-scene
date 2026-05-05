#!/usr/bin/env python3
"""
IR V2 — Prerequisite Check: Verify callback coverage.

Scans all .cs files used by the 26 patterns (scene + prefab scripts)
and extracts every method name defined. Cross-references against:
  1. TRACKED_CALLBACKS — the set our pipeline actually checks for
  2. ALL_KNOWN_UNITY_MESSAGES — a comprehensive (but not guaranteed
     exhaustive) list of MonoBehaviour messages from the Unity API

Reports:
  - Which Unity callbacks are actually used in this dataset
  - Whether TRACKED_CALLBACKS covers all of them
  - Any method names that match known Unity messages but are NOT tracked

This is a data-driven check: we do not claim our callback list is
exhaustive. We verify it against the actual codebase.

Reference:
  https://docs.unity3d.com/6000.3/Documentation/ScriptReference/MonoBehaviour.html

Input:
  data/processed/scene_analysis/<N>_<PatternName>_parsed.json
  data/raw/unity/.../Assets/Scripts/**/*.cs

Output:
  data/processed/scene_analysis/callback_coverage_report.md
  stdout: PASS/FAIL + summary

Usage:
    uv run python src/scene_analysis/v2/verify_callbacks.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ASSETS_DIR         = ROOT / "data" / "raw" / "unity" / "PatternsUnityCode" / "Assets"
SCRIPTS_DIR        = ASSETS_DIR / "Scripts"
PREFABS_DIR        = ASSETS_DIR / "Prefabs"
SCENE_ANALYSIS_DIR = ROOT / "data" / "processed" / "scene_analysis"

_GUID_RE = re.compile(r"^guid:\s*([0-9a-f]{32})", re.MULTILINE)
_PREFAB_BLOCK_RE = re.compile(r"^--- !u!(\d+) &(\d+)", re.MULTILINE)

# What our pipeline currently tracks in build_demand_manifest.py
TRACKED_CALLBACKS = {
    # Lifecycle
    "Awake", "Start", "Update", "FixedUpdate", "LateUpdate",
    "OnEnable", "OnDisable", "OnDestroy",
    # Physics — trigger
    "OnTriggerEnter2D", "OnTriggerExit2D", "OnTriggerStay2D",
    "OnTriggerEnter", "OnTriggerExit", "OnTriggerStay",
    # Physics — collision
    "OnCollisionEnter2D", "OnCollisionExit2D", "OnCollisionStay2D",
    "OnCollisionEnter", "OnCollisionExit", "OnCollisionStay",
    # Physics — joint
    "OnJointBreak", "OnJointBreak2D",
    # Physics — other
    "OnParticleCollision", "OnControllerColliderHit",
    # Mouse
    "OnMouseDown", "OnMouseDrag", "OnMouseUp",
    "OnMouseEnter", "OnMouseExit", "OnMouseOver", "OnMouseUpAsButton",
    # Editor / debug (no runtime effect, but are Unity callbacks)
    "OnDrawGizmos", "OnDrawGizmosSelected",
    # Visibility
    "OnBecameVisible", "OnBecameInvisible",
    # Application lifecycle
    "OnApplicationPause", "OnApplicationFocus", "OnApplicationQuit",
    # GUI / Animation / Validation
    "OnGUI", "OnValidate", "Reset",
    "OnAnimatorMove", "OnAnimatorIK",
}

# Comprehensive list of MonoBehaviour messages from Unity Scripting API.
# Source: https://docs.unity3d.com/6000.3/Documentation/ScriptReference/MonoBehaviour.html
# This list may not be 100% complete for all Unity versions, but covers
# all documented messages as of Unity 6000.3.
ALL_KNOWN_UNITY_MESSAGES = TRACKED_CALLBACKS | {
    # Mouse (additional)
    "OnMouseEnter", "OnMouseExit", "OnMouseOver", "OnMouseUpAsButton",
    # Visibility
    "OnBecameVisible", "OnBecameInvisible",
    # Application lifecycle
    "OnApplicationFocus", "OnApplicationPause", "OnApplicationQuit",
    # Rendering
    "OnPreRender", "OnPostRender", "OnRenderObject",
    "OnWillRenderObject", "OnRenderImage", "OnPreCull",
    # Animation
    "OnAnimatorMove", "OnAnimatorIK",
    # GUI
    "OnGUI",
    # Network (legacy)
    "OnConnectedToServer", "OnDisconnectedFromServer",
    "OnPlayerConnected", "OnPlayerDisconnected",
    "OnServerInitialized", "OnFailedToConnect",
    "OnNetworkInstantiate", "OnSerializeNetworkView",
    # Transform
    "OnTransformParentChanged", "OnTransformChildrenChanged",
    # Canvas
    "OnCanvasGroupChanged", "OnRectTransformDimensionsChange",
    "OnCanvasHierarchyChanged",
    # Editor
    "OnValidate", "Reset",
    "OnDrawGizmos", "OnDrawGizmosSelected",
    # Audio
    "OnAudioFilterRead",
}


def build_guid_to_class() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for meta in SCRIPTS_DIR.rglob("*.cs.meta"):
        text = meta.read_text(encoding="utf-8")
        m = _GUID_RE.search(text)
        if not m:
            continue
        cs = meta.with_suffix("")
        index[m.group(1)] = {
            "class_name": cs.stem,
            "source_file": str(cs.relative_to(ROOT)),
        }
    return index


def find_all_script_files(guid_to_class: dict[str, dict]) -> dict[str, str]:
    """Return { class_name: source_file } for all scripts used across all patterns."""
    result: dict[str, str] = {}

    for f in sorted(SCENE_ANALYSIS_DIR.glob("*_parsed.json")):
        with open(f, encoding="utf-8") as fh:
            parsed = json.load(fh)
        for blk in parsed["blocksByType"].get("MonoBehaviour", []):
            mb_data = blk["data"].get("MonoBehaviour", {})
            guid = mb_data.get("m_Script", {}).get("guid")
            if not guid:
                continue
            entry = guid_to_class.get(guid)
            if entry:
                result[entry["class_name"]] = entry["source_file"]

    # Also find prefab scripts
    for meta in PREFABS_DIR.rglob("*.prefab.meta"):
        prefab_path = meta.with_suffix("")
        if not prefab_path.exists():
            continue
        text = prefab_path.read_text(encoding="utf-8")
        headers = list(_PREFAB_BLOCK_RE.finditer(text))
        for i, h in enumerate(headers):
            if int(h.group(1)) != 114:
                continue
            body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
            body = text[h.end():body_end]
            gm = re.search(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})", body)
            if gm:
                entry = guid_to_class.get(gm.group(1))
                if entry:
                    result[entry["class_name"]] = entry["source_file"]

    return result


def extract_method_names(cs_path: Path) -> list[str]:
    """Extract all method names from a .cs file using regex."""
    if not cs_path.exists():
        return []
    text = cs_path.read_text(encoding="utf-8")
    sig_pattern = re.compile(
        r'(?:(?:public|private|protected|internal|override|virtual|static|abstract|async)\s+)*'
        r'(?:[\w<>\[\],]+\s+)+'
        r'(\w+)\s*\([^)]*\)\s*'
        r'(?:where\s+\w+[^{]*)?\{',
        re.MULTILINE,
    )
    names = []
    for m in sig_pattern.finditer(text):
        name = m.group(1)
        if name not in {"if", "while", "for", "foreach", "switch", "catch", "using"}:
            names.append(name)
    return names


def main():
    guid_to_class = build_guid_to_class()
    all_scripts = find_all_script_files(guid_to_class)

    print(f"Scanning {len(all_scripts)} scripts across all patterns + prefabs...\n")

    # Extract all methods from all scripts
    method_to_scripts: defaultdict[str, list[str]] = defaultdict(list)
    for class_name, source_file in sorted(all_scripts.items()):
        cs_path = ROOT / source_file
        methods = extract_method_names(cs_path)
        for method in methods:
            method_to_scripts[method].append(class_name)

    # Classify methods
    unity_found: dict[str, list[str]] = {}       # Unity message → [classes]
    tracked_found: dict[str, list[str]] = {}      # tracked callback → [classes]
    untracked_found: dict[str, list[str]] = {}    # known Unity message NOT in tracked → [classes]
    unknown_possible: dict[str, list[str]] = {}   # starts with On but not in any known list

    for method, classes in sorted(method_to_scripts.items()):
        is_tracked = method in TRACKED_CALLBACKS
        is_known   = method in ALL_KNOWN_UNITY_MESSAGES

        if is_known:
            unity_found[method] = classes
            if is_tracked:
                tracked_found[method] = classes
            else:
                untracked_found[method] = classes
        elif method.startswith("On") and len(method) > 3:
            unknown_possible[method] = classes

    # Verdict
    passed = len(untracked_found) == 0

    # Console output
    print("Unity callbacks found in dataset:")
    for method, classes in sorted(unity_found.items()):
        flag = "  " if method in TRACKED_CALLBACKS else "!!"
        print(f"  {flag} {method} ({len(classes)} scripts): {', '.join(classes)}")

    if untracked_found:
        print(f"\n!! {len(untracked_found)} Unity callback(s) found but NOT tracked by pipeline:")
        for method, classes in sorted(untracked_found.items()):
            print(f"     {method}: {', '.join(classes)}")

    if unknown_possible:
        print(f"\n?  {len(unknown_possible)} On* methods not in known Unity list (likely user-defined):")
        for method, classes in sorted(unknown_possible.items()):
            print(f"     {method}: {', '.join(classes)}")

    not_found = TRACKED_CALLBACKS - set(unity_found.keys())
    if not_found:
        print(f"\n   {len(not_found)} tracked callbacks not used by any script (coverage headroom):")
        for method in sorted(not_found):
            print(f"     {method}")

    # Write report
    report_path = SCENE_ANALYSIS_DIR / "callback_coverage_report.md"
    lines: list[str] = []
    lines.append("# Callback Coverage Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Scripts scanned:** {len(all_scripts)}")
    lines.append(f"**Unique methods found:** {len(method_to_scripts)}")
    lines.append(f"**Unity callbacks found:** {len(unity_found)}")
    lines.append("")

    if passed:
        lines.append("## Verdict: PASS")
        lines.append("")
        lines.append("All Unity callbacks used in this dataset are tracked by the pipeline.")
    else:
        lines.append("## Verdict: FAIL")
        lines.append("")
        lines.append("The following Unity callbacks are used in the dataset but NOT tracked:")
        lines.append("")
        for method, classes in sorted(untracked_found.items()):
            lines.append(f"- **`{method}`** — used in: {', '.join(classes)}")
        lines.append("")
        lines.append("The pipeline's `extract_callbacks_defined()` should be updated to include these.")

    lines.append("")
    lines.append("## Unity Callbacks Found")
    lines.append("")
    lines.append("| Callback | Tracked | Scripts | Used By |")
    lines.append("|----------|:-------:|--------:|---------|")
    for method in sorted(unity_found.keys()):
        classes = unity_found[method]
        tracked = "yes" if method in TRACKED_CALLBACKS else "**NO**"
        lines.append(f"| `{method}` | {tracked} | {len(classes)} | {', '.join(classes)} |")

    if not_found:
        lines.append("")
        lines.append("## Tracked but Not Used")
        lines.append("")
        lines.append("These callbacks are in the pipeline's tracked list but not used by any script.")
        lines.append("This is expected — they provide coverage for other datasets.")
        lines.append("")
        for method in sorted(not_found):
            lines.append(f"- `{method}`")

    if unknown_possible:
        lines.append("")
        lines.append("## Unrecognized `On*` Methods")
        lines.append("")
        lines.append("Methods starting with `On` that are not in the known Unity messages list.")
        lines.append("These are likely user-defined methods, not Unity callbacks.")
        lines.append("")
        for method, classes in sorted(unknown_possible.items()):
            lines.append(f"- `{method}` — {', '.join(classes)}")

    lines.append("")
    lines.append("---")
    lines.append(f"*Reference: [MonoBehaviour Scripting API](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/MonoBehaviour.html)*")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'PASS' if passed else 'FAIL'}: {'All' if passed else 'Not all'} Unity callbacks in dataset are tracked.")
    print(f"\nOutput: {report_path.relative_to(ROOT)}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
