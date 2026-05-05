#!/usr/bin/env python3
"""
Stage 4.1 automation: static analysis of C# scripts.

Reads _identity.json (source file paths, class names) and _inspector.json
(inspector scalars and refs) for each pattern. Extracts Unity lifecycle
callbacks and inter-script interactions via regex, builds a cross-script
call graph, and traces win/lose condition paths from GameManager.GameWin()
and GameManager.GameLose().

Output is a candidate analysis for human review — not a final IR.
The human reviewer confirms the condition path, filters UI scripts, and
supplies domain interpretation for meta.coding_notes.

Input:
  data/processed/scene_analysis/<pattern>_identity.json
  data/processed/scene_analysis/<pattern>_inspector.json

Output:
  data/processed/scene_analysis/<pattern>_analysis.json

Usage:
    uv run python src/scene_analysis/analyze_scripts.py            # all patterns
    uv run python src/scene_analysis/analyze_scripts.py 1_Ownership
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENE_ANALYSIS_DIR = ROOT / "data" / "processed" / "scene_analysis"

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

# Unity lifecycle callbacks to track
UNITY_CALLBACKS = {
    "Awake", "Start", "Update", "FixedUpdate", "LateUpdate",
    "OnEnable", "OnDisable", "OnDestroy",
    "OnTriggerEnter2D", "OnTriggerExit2D", "OnTriggerStay2D",
    "OnCollisionEnter2D", "OnCollisionExit2D", "OnCollisionStay2D",
    "OnMouseDown", "OnMouseDrag", "OnMouseUp", "OnMouseEnter", "OnMouseExit",
}

# UI-indicator GO name substrings — scripts on these GOs are UI boilerplate
UI_GO_NAMES = {"Canvas", "Text", "Button", "Panel", "EventSystem", "Image"}


# ── C# file parsing ───────────────────────────────────────────────────

def extract_class_info(text: str) -> dict:
    """Extract class name, base class, and whether it's a singleton."""
    class_m = re.search(
        r'public\s+class\s+(\w+)(?:\s*:\s*(\w+))?', text
    )
    class_name = class_m.group(1) if class_m else "Unknown"
    base_class  = class_m.group(2) if class_m and class_m.group(2) else None

    # Singleton: has 'public static ClassName instance'
    is_singleton = bool(re.search(
        rf'public\s+static\s+{class_name}\s+instance', text
    ))

    return {
        "class_name":   class_name,
        "base_class":   base_class,
        "is_singleton": is_singleton,
    }


def extract_methods(text: str) -> dict[str, dict]:
    """
    Extract all method definitions with their body text and starting line.
    Returns { method_name: { "start_line": int, "body": str } }.
    Uses brace counting to find method bodies.
    """
    lines = text.split("\n")
    # Build a char-offset → line-number map
    offset_to_line: list[int] = []
    for i, line in enumerate(lines, start=1):
        offset_to_line.extend([i] * (len(line) + 1))  # +1 for newline

    def line_of(offset: int) -> int:
        return offset_to_line[min(offset, len(offset_to_line) - 1)]

    # Match method signatures.
    # Access modifiers are optional — Unity callbacks like `void Update()` omit them.
    sig_pattern = re.compile(
        r'(?:(?:public|private|protected|internal|override|virtual|static|abstract|async)\s+)*'
        r'(?:[\w<>\[\],]+\s+)+'     # return type (one or more tokens ending with space)
        r'(\w+)\s*'                  # method name
        r'\([^)]*\)\s*'             # parameters
        r'(?:where\s+\w+[^{]*)?\{', # optional constraints + opening brace
        re.MULTILINE,
    )

    methods: dict[str, dict] = {}
    for m in sig_pattern.finditer(text):
        name = m.group(1)
        # Skip keywords that look like method names
        if name in {"if", "while", "for", "foreach", "switch", "catch", "using"}:
            continue

        brace_start = m.end() - 1  # position of '{'
        depth = 0
        i = brace_start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = text[brace_start + 1 : i]
                    methods[name] = {
                        "start_line": line_of(brace_start),
                        "body":       body,
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
    """
    Scan a method body for inter-script interactions.
    Returns a list of interaction dicts, each with a line number relative
    to the method start.
    """
    interactions: list[dict] = []
    body_lines = body.split("\n")

    def abs_line(body_line_idx: int) -> int:
        return method_start_line + body_line_idx

    for i, line in enumerate(body_lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        ln = abs_line(i)

        # FindObjectOfType<T>()
        m = re.search(r'FindObjectOfType<(\w+)>\(\)', line)
        if m:
            interactions.append({
                "type":       "runtime_lookup",
                "call":       m.group(0),
                "target_class": m.group(1),
                "line":       ln,
            })

        # FindWithTag("tag")
        m = re.search(r'FindWithTag\("(\w+)"\)', line)
        if m:
            interactions.append({
                "type":  "runtime_lookup",
                "call":  m.group(0),
                "tag":   m.group(1),
                "line":  ln,
            })

        # X.instance.field++ or X.instance.field--
        m = re.search(r'(\w+)\.instance\.(\w+)(\+\+|--)', line)
        if m:
            interactions.append({
                "type":         "singleton_write",
                "target_class": m.group(1),
                "field":        m.group(2),
                "op":           m.group(3),
                "line":         ln,
            })
            continue  # don't double-match as singleton_call

        # X.instance.Method() — singleton call
        m = re.search(r'(\w+)\.instance\.(\w+)\(', line)
        if m:
            interactions.append({
                "type":         "singleton_call",
                "target_class": m.group(1),
                "call":         m.group(2),
                "line":         ln,
            })

        # GetComponent[InChildren|InParent]<T>()
        m = re.search(r'(GetComponent(?:InChildren|InParent)?)<(\w+)>', line)
        if m:
            interactions.append({
                "type":      "get_component",
                "call":      m.group(1),
                "component": m.group(2),
                "line":      ln,
            })

        # Instantiate(
        if re.search(r'\bInstantiate\s*\(', line):
            interactions.append({
                "type": "instantiate",
                "line": ln,
                "raw":  stripped,
            })

        # InvokeRepeating("MethodName", ...)
        m = re.search(r'InvokeRepeating\("(\w+)"', line)
        if m:
            interactions.append({
                "type":   "invoke_repeating",
                "method": m.group(1),
                "line":   ln,
            })

        # CompareTag("X") or .tag == "X"
        m = re.search(r'CompareTag\("(\w+)"\)|\.tag\s*==\s*"(\w+)"', line)
        if m:
            tag = m.group(1) or m.group(2)
            interactions.append({
                "type": "tag_check",
                "tag":  tag,
                "line": ln,
            })

        # if (...) — capture guard condition
        m = re.search(r'\bif\s*\((.+)\)', line)
        if m:
            interactions.append({
                "type":      "condition",
                "expr":      m.group(1).strip(),
                "line":      ln,
            })

    return interactions


def analyze_cs_file(cs_path: Path) -> dict:
    """
    Full analysis of a single .cs file.
    Returns structured info about the class and its interactions.
    """
    text = cs_path.read_text(encoding="utf-8")
    class_info = extract_class_info(text)
    methods     = extract_methods(text)

    callbacks:      dict[str, list] = {}
    other_methods:  dict[str, list] = {}

    for method_name, mdata in methods.items():
        interactions = extract_interactions(
            method_name, mdata["body"], mdata["start_line"],
            class_info["class_name"]
        )
        if method_name in UNITY_CALLBACKS:
            callbacks[method_name] = {
                "start_line":   mdata["start_line"],
                "interactions": interactions,
            }
        else:
            other_methods[method_name] = {
                "start_line":   mdata["start_line"],
                "interactions": interactions,
            }

    return {
        **class_info,
        "source_file": str(cs_path.relative_to(ROOT)),
        "callbacks":   callbacks,
        "methods":     other_methods,
    }


# ── cross-script analysis ─────────────────────────────────────────────

def collect_source_files(identity: dict) -> dict[str, str]:
    """
    Return { class_name: source_file_path } for all resolved scripts
    in a pattern's _identity.json.
    """
    result: dict[str, str] = {}
    for mb in identity["monobehaviours"].values():
        if mb["class_name"] and mb["source_file"]:
            result[mb["class_name"]] = mb["source_file"]
    for ref in identity.get("prefab_refs", []):
        for mb in ref["prefab_monobehaviours"].values():
            if mb["class_name"] and mb["source_file"]:
                result[mb["class_name"]] = mb["source_file"]
    return result


def identify_ui_scripts(identity: dict) -> list[dict]:
    """
    Return list of { class_name, go_name, source_file, evidence } for scripts
    that sit on UI GOs (Canvas, Text, etc.). Candidates for exclusion from IR.
    """
    seen: set[str] = set()
    ui: list[dict] = []
    for mb in identity["monobehaviours"].values():
        if not mb["class_name"]:
            continue
        go_name = mb.get("go_name", "")
        if any(ui_kw in go_name for ui_kw in UI_GO_NAMES):
            if mb["class_name"] not in seen:
                seen.add(mb["class_name"])
                ui.append({
                    "class_name":  mb["class_name"],
                    "go_name":     go_name,
                    "source_file": mb.get("source_file"),
                    "evidence":    f"GO name '{go_name}' matches UI keyword",
                })
    return ui


def _trace_path_for_call(
    all_scripts: dict[str, dict],
    target_method: str,
    step_label: str,
) -> list[dict]:
    """
    Generic path tracer: find all callers of GameManager.instance.<target_method>(),
    then trace upstream singleton_writes that feed into those callers.
    Returns an ordered list of path steps (counter_update first, trigger last).
    """
    path: list[dict] = []

    # Step 1: who calls GameManager.instance.<target_method>() ?
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
                            "event":       scope_name,
                            "line":        ix["line"],
                            "source_file": script["source_file"],
                        })

    if not direct_callers:
        return []

    caller_classes = {c["actor_class"] for c in direct_callers}

    # Step 2: build trigger steps
    for caller in direct_callers:
        actor  = caller["actor_class"]
        script = all_scripts.get(actor, {})
        cb_name = caller["event"]
        cb_data = (script.get("callbacks", {}).get(cb_name)
                   or script.get("methods", {}).get(cb_name, {}))
        conditions = [
            ix["expr"] for ix in cb_data.get("interactions", [])
            if ix["type"] == "condition"
        ]
        path.append({
            "step":        step_label,
            "actor_class": actor,
            "event":       cb_name,
            "conditions":  conditions,
            "effect":      f"GameManager.instance.{target_method}()",
            "evidence":    f"{script.get('source_file', '')}:{caller['line']}",
        })

    # Step 3: who writes to a counter/state field on a caller-class singleton?
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
                        path.insert(0, {
                            "step":        "counter_update",
                            "actor_class": class_name,
                            "event":       cb_name,
                            "conditions":  conditions,
                            "effect":      f"{target}.instance.{ix['field']}{ix['op']}",
                            "evidence":    f"{script['source_file']}:{ix['line']}",
                        })
    return path


def trace_win_path(all_scripts: dict[str, dict]) -> dict:
    """
    Trace win and lose condition paths.
    Returns { "win": [...], "lose": [...] }.
    Patterns with only a lose path (Evade, Guard, Survive) will have win=[].
    """
    return {
        "win":  _trace_path_for_call(all_scripts, "GameWin",  "win_trigger"),
        "lose": _trace_path_for_call(all_scripts, "GameLose", "lose_trigger"),
    }


def detect_spawn_plan(
    all_scripts: dict[str, dict],
    identity: dict,
    inspector: dict,
) -> dict | None:
    """
    Detect an active SpawnManager (or equivalent spawner) and return its plan.
    Returns None if no active spawner found.

    inspector["monobehaviours"] — scalars, refs, go_name per MB fileID
    identity["prefab_refs"]     — expanded prefab structure with class names
    """
    # Find SpawnManager MB in scene via inspector (has class_name + scalars)
    for mb_fid, mb in inspector["monobehaviours"].items():
        if mb.get("class_name") != "SpawnManager":
            continue
        scalars = mb.get("inspector_scalars", {})
        spawn_start = scalars.get("spawnStart", 0)
        if not spawn_start:
            return None  # spawnStart == false → inert

        # Find prefab ref — inspector_refs has target_type/to_prefab_id;
        # prefab_monobehaviours (with class names) live in identity.prefab_refs
        prefab_name    = None
        prefab_classes: list[str] = []
        for ref in mb.get("inspector_refs", []):
            if ref.get("target_type") == "to_prefab_id":
                prefab_name = ref.get("to_prefab_id")
                break
        if prefab_name:
            for id_ref in identity.get("prefab_refs", []):
                if id_ref["from_mb"] == mb_fid:
                    prefab_classes = [
                        m["class_name"]
                        for m in id_ref["prefab_monobehaviours"].values()
                        if m["class_name"]
                    ]
                    break

        return {
            "spawner_class":  "SpawnManager",
            "spawner_go":     mb.get("go_name"),
            "prefab_name":    prefab_name,
            "prefab_scripts": prefab_classes,
            "count":          scalars.get("spawnCount"),
            "spawn_range_x":  scalars.get("spawnRangeX"),
            "spawn_range_y":  scalars.get("spawnRangeY"),
            "timing":         "on_start",
            "repeating":      bool(scalars.get("spawnRepeat", 0)),
            "repeat_rate":    scalars.get("spawnRepeatRate"),
        }
    return None


# ── per-pattern analysis ──────────────────────────────────────────────

def analyze_pattern(pattern: str) -> dict | None:
    identity_path  = SCENE_ANALYSIS_DIR / f"{pattern}_identity.json"
    inspector_path = SCENE_ANALYSIS_DIR / f"{pattern}_inspector.json"
    if not identity_path.exists() or not inspector_path.exists():
        return None

    with open(identity_path, encoding="utf-8") as f:
        identity = json.load(f)
    with open(inspector_path, encoding="utf-8") as f:
        inspector = json.load(f)

    # Collect source files from identity (has source_file paths)
    source_files = collect_source_files(identity)

    # Analyze each .cs file
    all_scripts: dict[str, dict] = {}
    for class_name, rel_path in source_files.items():
        cs_path = ROOT / rel_path
        if not cs_path.exists():
            continue
        info = analyze_cs_file(cs_path)
        # Override class name from identity (more reliable than regex)
        info["class_name"] = class_name
        all_scripts[class_name] = info

    # Cross-script analysis
    ui_scripts = identify_ui_scripts(identity)
    win_path   = trace_win_path(all_scripts)
    spawn_plan = detect_spawn_plan(all_scripts, identity, inspector)

    return {
        "scene":          pattern,
        "scripts":        all_scripts,
        "condition_path": win_path,   # { "win": [...], "lose": [...] }
        "spawn_plan":     spawn_plan,
        "ui_scripts":     sorted(ui_scripts, key=lambda x: x["class_name"]),
        "go_tags":        inspector.get("go_tags", {}),
        "note":           "Candidate output for human review. Confirm condition_path, verify ui_scripts exclusions, add meta.coding_notes.",
    }


# ── main ──────────────────────────────────────────────────────────────

def main():
    patterns = sys.argv[1:] if len(sys.argv) > 1 else ALL_PATTERNS
    ok = 0
    for pattern in patterns:
        result = analyze_pattern(pattern)
        if result is None:
            print(f"  SKIP  {pattern} (no _identity.json or _inspector.json)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_analysis.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        n_scripts  = len(result["scripts"])
        cpath      = result["condition_path"]
        n_win      = len(cpath["win"])
        n_lose     = len(cpath["lose"])
        n_ui       = len(result["ui_scripts"])
        spawn_info = result["spawn_plan"]["prefab_name"] if result["spawn_plan"] else "none"

        flag = "  !" if (n_win == 0 and n_lose == 0) else "   "
        print(f"{flag} {pattern}: {n_scripts} scripts, "
              f"win={n_win} lose={n_lose}, spawn={spawn_info}, ui_excluded={n_ui}")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns analyzed.")


if __name__ == "__main__":
    main()
