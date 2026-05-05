#!/usr/bin/env python3
"""
IR V2 — Pass 3: Condition Path Tracing

Reads the demand manifest to know which scripts to analyze, then
performs deep static analysis of those .cs files to reconstruct
the ordered win/lose condition paths with line-level evidence.

The condition path answers: "What sequence of events, starting from
a Unity callback, leads to GameManager.GameWin() or GameManager.GameLose()?"

Each step in the path records:
  - which class and method
  - what conditions guard it
  - what effect it produces
  - exact source file and line number as evidence

Input:
  data/processed/scene_analysis/<pattern>_manifest.json
  .cs files referenced in the manifest

Output:
  data/processed/scene_analysis/<pattern>_condition_path.json

Usage:
    uv run python src/scene_analysis/v2/trace_condition_path.py
    uv run python src/scene_analysis/v2/trace_condition_path.py 1_Ownership
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

UNITY_CALLBACKS = {
    "Awake", "Start", "Update", "FixedUpdate", "LateUpdate",
    "OnEnable", "OnDisable", "OnDestroy",
    "OnTriggerEnter2D", "OnTriggerExit2D", "OnTriggerStay2D",
    "OnTriggerEnter", "OnTriggerExit", "OnTriggerStay",
    "OnCollisionEnter2D", "OnCollisionExit2D", "OnCollisionStay2D",
    "OnCollisionEnter", "OnCollisionExit", "OnCollisionStay",
    "OnJointBreak", "OnJointBreak2D",
    "OnParticleCollision", "OnControllerColliderHit",
    "OnMouseDown", "OnMouseDrag", "OnMouseUp",
    "OnMouseEnter", "OnMouseExit", "OnMouseOver", "OnMouseUpAsButton",
    "OnDrawGizmos", "OnDrawGizmosSelected",
    "OnBecameVisible", "OnBecameInvisible",
    "OnApplicationPause", "OnApplicationFocus", "OnApplicationQuit",
    "OnGUI", "OnValidate", "Reset",
    "OnAnimatorMove", "OnAnimatorIK",
}


# ── C# static analysis ───────────────────────────────────────────────

def extract_class_info(text: str) -> dict:
    class_m = re.search(r'public\s+class\s+(\w+)(?:\s*:\s*(\w+))?', text)
    class_name = class_m.group(1) if class_m else "Unknown"
    base_class = class_m.group(2) if class_m and class_m.group(2) else None
    is_singleton = bool(re.search(
        rf'public\s+static\s+{class_name}\s+instance', text
    ))
    return {
        "class_name": class_name,
        "base_class": base_class,
        "is_singleton": is_singleton,
    }


def extract_methods(text: str) -> dict[str, dict]:
    lines = text.split("\n")
    offset_to_line: list[int] = []
    for i, line in enumerate(lines, start=1):
        offset_to_line.extend([i] * (len(line) + 1))

    def line_of(offset: int) -> int:
        return offset_to_line[min(offset, len(offset_to_line) - 1)]

    sig_pattern = re.compile(
        r'(?:(?:public|private|protected|internal|override|virtual|static|abstract|async)\s+)*'
        r'(?:[\w<>\[\],]+\s+)+'
        r'(\w+)\s*'
        r'\([^)]*\)\s*'
        r'(?:where\s+\w+[^{]*)?\{',
        re.MULTILINE,
    )

    methods: dict[str, dict] = {}
    for m in sig_pattern.finditer(text):
        name = m.group(1)
        if name in {"if", "while", "for", "foreach", "switch", "catch", "using"}:
            continue
        brace_start = m.end() - 1
        depth = 0
        i = brace_start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    methods[name] = {
                        "start_line": line_of(brace_start),
                        "body": text[brace_start + 1 : i],
                    }
                    break
            i += 1
    return methods


def extract_interactions(
    method_name: str,
    body: str,
    method_start_line: int,
    class_name: str,
) -> list[dict]:
    interactions: list[dict] = []
    body_lines = body.split("\n")

    def abs_line(idx: int) -> int:
        return method_start_line + idx

    for i, line in enumerate(body_lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        ln = abs_line(i)

        m = re.search(r'FindObjectOfType<(\w+)>\(\)', line)
        if m:
            interactions.append({
                "type": "runtime_lookup", "call": m.group(0),
                "target_class": m.group(1), "line": ln,
            })

        m = re.search(r'FindWithTag\("(\w+)"\)', line)
        if m:
            interactions.append({
                "type": "runtime_lookup", "call": m.group(0),
                "tag": m.group(1), "line": ln,
            })

        m = re.search(r'(\w+)\.instance\.(\w+)(\+\+|--)', line)
        if m:
            interactions.append({
                "type": "singleton_write", "target_class": m.group(1),
                "field": m.group(2), "op": m.group(3), "line": ln,
            })
            continue

        m = re.search(r'(\w+)\.instance\.(\w+)\(', line)
        if m:
            interactions.append({
                "type": "singleton_call", "target_class": m.group(1),
                "call": m.group(2), "line": ln,
            })

        m = re.search(r'(GetComponent(?:InChildren|InParent)?)<(\w+)>', line)
        if m:
            interactions.append({
                "type": "get_component", "call": m.group(1),
                "component": m.group(2), "line": ln,
            })

        if re.search(r'\bInstantiate\s*\(', line):
            interactions.append({
                "type": "instantiate", "line": ln, "raw": stripped,
            })

        m = re.search(r'InvokeRepeating\("(\w+)"', line)
        if m:
            interactions.append({
                "type": "invoke_repeating", "method": m.group(1), "line": ln,
            })

        m = re.search(r'CompareTag\("(\w+)"\)|\.tag\s*==\s*"(\w+)"', line)
        if m:
            interactions.append({
                "type": "tag_check", "tag": m.group(1) or m.group(2), "line": ln,
            })

        m = re.search(r'\bif\s*\((.+)\)', line)
        if m:
            interactions.append({
                "type": "condition", "expr": m.group(1).strip(), "line": ln,
            })

    return interactions


def analyze_cs_file(cs_path: Path) -> dict:
    text = cs_path.read_text(encoding="utf-8")
    class_info = extract_class_info(text)
    methods = extract_methods(text)

    callbacks: dict[str, dict] = {}
    other_methods: dict[str, dict] = {}

    for method_name, mdata in methods.items():
        interactions = extract_interactions(
            method_name, mdata["body"], mdata["start_line"],
            class_info["class_name"],
        )
        entry = {
            "start_line": mdata["start_line"],
            "body": mdata["body"],
            "interactions": interactions,
        }
        if method_name in UNITY_CALLBACKS:
            callbacks[method_name] = entry
        else:
            other_methods[method_name] = entry

    return {
        **class_info,
        "source_file": str(cs_path.relative_to(ROOT)),
        "callbacks": callbacks,
        "methods": other_methods,
    }


# ── condition path tracing ────────────────────────────────────────────

def _get_method_source(script: dict, method_name: str) -> str | None:
    """Get the full method body text for display in the review brief."""
    for scope_dict in [script.get("callbacks", {}), script.get("methods", {})]:
        if method_name in scope_dict:
            return scope_dict[method_name].get("body")
    return None


def _trace_path_for_call(
    all_scripts: dict[str, dict],
    target_method: str,
    step_label: str,
) -> list[dict]:
    """
    Find all callers of GameManager.instance.<target_method>(),
    then trace upstream singleton_writes that feed into those callers.
    Returns ordered path steps (counter_update first, trigger last).
    Each step includes the full method body for review context.
    """
    path: list[dict] = []

    direct_callers: list[dict] = []
    for class_name, script in all_scripts.items():
        for scope_dict in [script["callbacks"], script["methods"]]:
            for scope_name, scope_data in scope_dict.items():
                for ix in scope_data["interactions"]:
                    if (ix["type"] == "singleton_call"
                            and ix.get("target_class") == "GameManager"
                            and ix.get("call") == target_method):
                        direct_callers.append({
                            "actor_class": class_name,
                            "event": scope_name,
                            "line": ix["line"],
                            "source_file": script["source_file"],
                        })

    if not direct_callers:
        return []

    caller_classes = {c["actor_class"] for c in direct_callers}

    for caller in direct_callers:
        actor = caller["actor_class"]
        script = all_scripts.get(actor, {})
        cb_name = caller["event"]
        cb_data = (script.get("callbacks", {}).get(cb_name)
                   or script.get("methods", {}).get(cb_name, {}))
        conditions = [
            ix["expr"] for ix in cb_data.get("interactions", [])
            if ix["type"] == "condition"
        ]
        body = _get_method_source(script, cb_name)
        path.append({
            "step": step_label,
            "actor_class": actor,
            "event": cb_name,
            "conditions": conditions,
            "effect": f"GameManager.instance.{target_method}()",
            "evidence": f"{script.get('source_file', '')}:{caller['line']}",
            "method_body": body,
        })

    for class_name, script in all_scripts.items():
        if class_name in caller_classes:
            continue
        for cb_name, cb_data in script["callbacks"].items():
            for ix in cb_data["interactions"]:
                if ix["type"] == "singleton_write":
                    target = ix.get("target_class", "")
                    if target in caller_classes:
                        conditions = [
                            jx["expr"] for jx in cb_data["interactions"]
                            if jx["type"] == "condition"
                        ]
                        body = _get_method_source(script, cb_name)
                        path.insert(0, {
                            "step": "counter_update",
                            "actor_class": class_name,
                            "event": cb_name,
                            "conditions": conditions,
                            "effect": f"{target}.instance.{ix['field']}{ix['op']}",
                            "evidence": f"{script['source_file']}:{ix['line']}",
                            "method_body": body,
                        })
    return path


def trace_condition_paths(all_scripts: dict[str, dict]) -> dict:
    return {
        "win": _trace_path_for_call(all_scripts, "GameWin", "win_trigger"),
        "lose": _trace_path_for_call(all_scripts, "GameLose", "lose_trigger"),
    }


# ── per-pattern ───────────────────────────────────────────────────────

def trace_pattern(pattern: str) -> dict | None:
    manifest_path = SCENE_ANALYSIS_DIR / f"{pattern}_manifest.json"
    if not manifest_path.exists():
        return None

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    all_scripts: dict[str, dict] = {}
    for class_name, sinfo in manifest["scripts"].items():
        cs_path = ROOT / sinfo["source_file"]
        if not cs_path.exists():
            continue
        info = analyze_cs_file(cs_path)
        info["class_name"] = class_name
        all_scripts[class_name] = info

    condition_paths = trace_condition_paths(all_scripts)

    return {
        "pattern": pattern,
        "condition_path": condition_paths,
        "scripts_analyzed": len(all_scripts),
    }


# ── main ──────────────────────────────────────────────────────────────

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
        result = trace_pattern(pattern)
        if result is None:
            print(f"  SKIP  {pattern} (no _manifest.json)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_condition_path.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        cp = result["condition_path"]
        n_win = len(cp["win"])
        n_lose = len(cp["lose"])
        print(f"  {pattern}: win={n_win} steps, lose={n_lose} steps")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns.")


if __name__ == "__main__":
    main()
