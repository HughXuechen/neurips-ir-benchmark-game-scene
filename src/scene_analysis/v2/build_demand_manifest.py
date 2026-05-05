#!/usr/bin/env python3
"""
IR V2 — Pass 1: Demand Manifest

Statically analyzes the C# scripts used in a scene and produces a
demand manifest: what scene data the scripts actually reference.

The manifest answers: which tags, which inspector fields, which
component types, and which prefab references do the scripts use?
No component types are excluded a priori — the scripts determine
what is relevant.

Pass 2 (extract_demanded.py) reads this manifest and queries
_parsed.json for exactly the demanded data.

Input:
  data/processed/scene_analysis/<pattern>_parsed.json
  data/raw/unity/.../Assets/Scripts/**/*.cs  (via .cs.meta GUID index)

Output:
  data/processed/scene_analysis/<pattern>_manifest.json

Usage:
    uv run python src/scene_analysis/v2/build_demand_manifest.py
    uv run python src/scene_analysis/v2/build_demand_manifest.py 1_Ownership
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ASSETS_DIR         = ROOT / "data" / "raw" / "unity" / "PatternsUnityCode" / "Assets"
SCRIPTS_DIR        = ASSETS_DIR / "Scripts"
PREFABS_DIR        = ASSETS_DIR / "Prefabs"
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

_GUID_RE = re.compile(r"^guid:\s*([0-9a-f]{32})", re.MULTILINE)
_PREFAB_BLOCK_RE = re.compile(r"^--- !u!(\d+) &(\d+)", re.MULTILINE)

# Unity physics callbacks — their presence implies Collider/Rigidbody dependency.
# Complete list per Unity Scripting API: MonoBehaviour
# https://docs.unity3d.com/6000.3/Documentation/ScriptReference/MonoBehaviour.html
#
# Covered here: Trigger (6), Collision (6), Joint (2), Particle (1), Controller (1).
# The 26 patterns only use OnTriggerEnter2D and OnCollisionEnter2D, but all 16
# are listed for correctness on other datasets.
TRIGGER_CALLBACKS   = {"OnTriggerEnter2D", "OnTriggerExit2D", "OnTriggerStay2D",
                       "OnTriggerEnter",   "OnTriggerExit",   "OnTriggerStay"}
COLLISION_CALLBACKS = {"OnCollisionEnter2D", "OnCollisionExit2D", "OnCollisionStay2D",
                       "OnCollisionEnter",   "OnCollisionExit",   "OnCollisionStay"}
JOINT_CALLBACKS     = {"OnJointBreak", "OnJointBreak2D"}
OTHER_PHYSICS_CALLBACKS = {"OnParticleCollision", "OnControllerColliderHit"}


# ── GUID indexes ──────────────────────────────────────────────────────

def build_guid_to_class(scripts_dir: Path) -> dict[str, dict]:
    """{ guid: { class_name, source_file } } from all .cs.meta files."""
    index: dict[str, dict] = {}
    for meta in scripts_dir.rglob("*.cs.meta"):
        text = meta.read_text(encoding="utf-8")
        m = _GUID_RE.search(text)
        if not m:
            continue
        cs = meta.with_suffix("")
        index[m.group(1)] = {
            "class_name":  cs.stem,
            "source_file": str(cs.relative_to(ROOT)),
        }
    return index


def build_guid_to_prefab(prefabs_dir: Path) -> dict[str, dict]:
    """{ guid: { prefab_name, prefab_path } } from all .prefab.meta files."""
    index: dict[str, dict] = {}
    for meta in prefabs_dir.rglob("*.prefab.meta"):
        text = meta.read_text(encoding="utf-8")
        m = _GUID_RE.search(text)
        if not m:
            continue
        prefab = meta.with_suffix("")
        index[m.group(1)] = {
            "prefab_name": prefab.stem,
            "prefab_path": str(prefab.relative_to(ROOT)),
        }
    return index


# ── .cs static analysis ───────────────────────────────────────────────

def extract_field_declarations(text: str) -> list[dict]:
    """
    Extract class-level field declarations that Unity will serialize
    to the Inspector:
      - public <type> <name>  (non-static, non-const)
      - [SerializeField] ... private/protected <type> <name>

    Returns [ { name, type, is_object_ref } ]
    where is_object_ref is True for GameObject/Component/MonoBehaviour
    subclasses and Unity Object types (detectable by capitalized type).
    """
    pat = re.compile(
        r'(?:\[SerializeField\]\s*(?:\[.*?\]\s*)?)?'   # optional [SerializeField] + other attrs
        r'(public|private|protected|internal)\s+'
        r'(?:static\s+|readonly\s+|const\s+)*'
        r'([\w<>\[\]]+)\s+'                            # type
        r'(\w+)'                                       # field name
        r'\s*(?:=\s*[^;{]+)?;',                       # optional initialiser, then ;
        re.MULTILINE,
    )
    fields = []
    for m in pat.finditer(text):
        access, typ, name = m.group(1), m.group(2), m.group(3)
        # Skip non-serialized: private without [SerializeField]
        preceding = text[max(0, m.start()-60):m.start()]
        has_sf = "[SerializeField]" in preceding
        if access != "public" and not has_sf:
            continue
        # Skip const / static (not serialized)
        between = text[m.start():m.start() + m.end() - m.start()]
        if "const " in between or "static " in between:
            continue
        # Skip keywords captured as field names
        if name in {"if", "for", "while", "return", "class", "void"}:
            continue
        # Object ref heuristic: type starts with uppercase (Unity Objects, GameObjects, etc.)
        is_ref = typ[0].isupper() if typ else False
        fields.append({"name": name, "type": typ, "is_object_ref": is_ref})
    return fields


def extract_tags_checked(text: str) -> list[str]:
    tags = []
    for m in re.finditer(r'CompareTag\("(\w+)"\)|\.tag\s*==\s*"(\w+)"', text):
        tags.append(m.group(1) or m.group(2))
    return list(set(tags))


def extract_get_component_types(text: str) -> list[str]:
    return list(set(re.findall(r'GetComponent(?:InChildren|InParent)?<(\w+)>', text)))


def extract_singleton_calls(text: str) -> list[dict]:
    calls = []
    for m in re.finditer(r'(\w+)\.instance\.(\w+)\s*\(', text):
        calls.append({"class": m.group(1), "method": m.group(2)})
    return calls


def extract_singleton_writes(text: str) -> list[dict]:
    writes = []
    for m in re.finditer(r'(\w+)\.instance\.(\w+)(\+\+|--|[+\-*/]?=)', text):
        writes.append({"class": m.group(1), "field": m.group(2)})
    return writes


def extract_callbacks_defined(text: str) -> list[str]:
    """Return names of Unity callback methods defined in this file."""
    all_callbacks = (
        {"Awake", "Start", "Update", "FixedUpdate", "LateUpdate",
         "OnEnable", "OnDisable", "OnDestroy",
         "OnMouseDown", "OnMouseDrag", "OnMouseUp",
         "OnMouseEnter", "OnMouseExit", "OnMouseOver", "OnMouseUpAsButton",
         "OnDrawGizmos", "OnDrawGizmosSelected",
         "OnBecameVisible", "OnBecameInvisible",
         "OnApplicationPause", "OnApplicationFocus", "OnApplicationQuit",
         "OnGUI", "OnValidate", "Reset",
         "OnAnimatorMove", "OnAnimatorIK"}
        | TRIGGER_CALLBACKS | COLLISION_CALLBACKS
        | JOINT_CALLBACKS | OTHER_PHYSICS_CALLBACKS
    )
    found = []
    for cb in all_callbacks:
        if re.search(rf'\b{cb}\s*\(', text):
            found.append(cb)
    return found


def analyze_cs(source_file: str) -> dict:
    """Full static analysis of one .cs file for V2 demand extraction."""
    path = ROOT / source_file
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")

    callbacks  = extract_callbacks_defined(text)
    tags       = extract_tags_checked(text)
    gc_types   = extract_get_component_types(text)
    sc_calls   = extract_singleton_calls(text)
    sc_writes  = extract_singleton_writes(text)
    fields     = extract_field_declarations(text)

    # Implied component dependencies from physics callbacks
    implied_components: list[str] = []
    if any(cb in TRIGGER_CALLBACKS for cb in callbacks):
        implied_components.append("Collider2D_or_Collider_trigger")
    if any(cb in COLLISION_CALLBACKS for cb in callbacks):
        implied_components.append("Collider2D_or_Collider_solid")
    if any(cb in JOINT_CALLBACKS for cb in callbacks):
        implied_components.append("Joint2D_or_Joint")
    if "OnParticleCollision" in callbacks:
        implied_components.append("ParticleSystem")
    if "OnControllerColliderHit" in callbacks:
        implied_components.append("CharacterController")

    return {
        "callbacks":           callbacks,
        "tags_checked":        tags,
        "get_component_types": gc_types,
        "singleton_calls":     sc_calls,
        "singleton_writes":    sc_writes,
        "field_declarations":  fields,
        "implied_components":  implied_components,
    }


# ── prefab script expansion ───────────────────────────────────────────

def scripts_in_prefab(prefab_path: Path, guid_to_class: dict[str, dict]) -> list[str]:
    """Return class names of all MB scripts inside a prefab asset."""
    if not prefab_path.exists():
        return []
    text = prefab_path.read_text(encoding="utf-8")
    headers = list(_PREFAB_BLOCK_RE.finditer(text))
    names = []
    for i, h in enumerate(headers):
        if int(h.group(1)) != 114:  # MonoBehaviour
            continue
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[h.end():body_end]
        gm = re.search(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})", body)
        if gm:
            entry = guid_to_class.get(gm.group(1), {})
            if entry.get("class_name"):
                names.append(entry["class_name"])
    return names


# ── per-pattern manifest ──────────────────────────────────────────────

def prefab_scripts_with_source(
    prefab_path: Path,
    guid_to_class: dict[str, dict],
) -> list[dict]:
    """Return [ { class_name, source_file } ] for all MB scripts inside a prefab."""
    if not prefab_path.exists():
        return []
    text = prefab_path.read_text(encoding="utf-8")
    headers = list(_PREFAB_BLOCK_RE.finditer(text))
    results = []
    for i, h in enumerate(headers):
        if int(h.group(1)) != 114:
            continue
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[h.end():body_end]
        gm = re.search(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})", body)
        if not gm:
            continue
        entry = guid_to_class.get(gm.group(1), {})
        if entry.get("class_name"):
            results.append(entry)
    return results


def build_manifest(
    pattern: str,
    guid_to_class: dict[str, dict],
    guid_to_prefab: dict[str, dict],
) -> dict | None:
    parsed_path = SCENE_ANALYSIS_DIR / f"{pattern}_parsed.json"
    if not parsed_path.exists():
        return None

    with open(parsed_path, encoding="utf-8") as f:
        parsed = json.load(f)

    # Map GO fileID → GO name
    go_names: dict[str, str] = {
        str(blk["fileID"]): blk["data"].get("GameObject", {}).get("m_Name", "")
        for blk in parsed["blocksByType"].get("GameObject", [])
    }

    # For each MB: resolve guid → class; record GO parent
    scene_scripts: dict[str, dict] = {}   # class_name → info
    mb_to_go: dict[str, str] = {}         # mb_fid → go_fid

    for blk in parsed["blocksByType"].get("MonoBehaviour", []):
        mb_fid  = str(blk["fileID"])
        mb_data = blk["data"].get("MonoBehaviour", {})
        guid    = mb_data.get("m_Script", {}).get("guid")
        go_fid  = str(mb_data.get("m_GameObject", {}).get("fileID", 0))
        mb_to_go[mb_fid] = go_fid

        if not guid:
            continue
        entry = guid_to_class.get(guid, {})
        class_name = entry.get("class_name")
        if not class_name:
            continue  # Unity built-in

        yaml_fields = {
            k: v for k, v in mb_data.items()
            if not k.startswith("m_")
        }

        scene_scripts[class_name] = {
            "source_file":  entry["source_file"],
            "mb_fid":       mb_fid,
            "go_fid":       go_fid,
            "go_name":      go_names.get(go_fid, ""),
            "yaml_fields":  yaml_fields,
            "origin":       "scene",
        }

    # ── static analysis of scene scripts ─────────────────────────────
    analyzed: dict[str, dict] = {}
    for class_name, info in scene_scripts.items():
        analysis = analyze_cs(info["source_file"])
        analyzed[class_name] = {**info, **analysis}

    # ── discover and analyze prefab scripts ───────────────────────────
    # For every object-ref field in scene MB YAML that points to a prefab,
    # find the scripts inside that prefab and analyze them too.
    prefab_script_entries: dict[str, dict] = {}  # class_name → {source_file, prefab_name}
    for class_name, a in analyzed.items():
        for fname, fval in a.get("yaml_fields", {}).items():
            if not isinstance(fval, dict):
                continue
            guid = fval.get("guid")
            if not guid or guid not in guid_to_prefab:
                continue
            pinfo    = guid_to_prefab[guid]
            p_path   = ROOT / pinfo["prefab_path"]
            for entry in prefab_scripts_with_source(p_path, guid_to_class):
                cname = entry["class_name"]
                if cname not in analyzed and cname not in prefab_script_entries:
                    prefab_script_entries[cname] = {
                        "source_file": entry["source_file"],
                        "prefab_name": pinfo["prefab_name"],
                        "origin":      "prefab",
                    }

    for class_name, info in prefab_script_entries.items():
        analysis = analyze_cs(info["source_file"])
        analyzed[class_name] = {**info, **analysis}

    # ── aggregate demands ─────────────────────────────────────────────

    # 1. Tags
    all_tags: set[str] = set()
    for a in analyzed.values():
        all_tags.update(a.get("tags_checked", []))

    # 2. Inspector fields: intersection of field_declarations × yaml_fields
    #    These are fields declared in .cs AND present in the YAML → confirmed inspector-exposed
    inspector_fields: dict[str, list[str]] = {}
    for class_name, a in analyzed.items():
        declared = {f["name"] for f in a.get("field_declarations", [])}
        in_yaml  = set(a.get("yaml_fields", {}).keys())
        confirmed = sorted(declared & in_yaml)
        if confirmed:
            inspector_fields[class_name] = confirmed

    # 3. Object-ref inspector fields → check if they point to prefabs
    prefab_refs: dict[str, list[dict]] = {}   # class_name → [{field, prefab_name}]
    for class_name, a in analyzed.items():
        refs = []
        for fname, fval in a.get("yaml_fields", {}).items():
            if not isinstance(fval, dict):
                continue
            guid = fval.get("guid")
            if guid and guid in guid_to_prefab:
                pinfo = guid_to_prefab[guid]
                prefab_path = ROOT / pinfo["prefab_path"]
                prefab_scripts = scripts_in_prefab(prefab_path, guid_to_class)
                refs.append({
                    "field":          fname,
                    "prefab_name":    pinfo["prefab_name"],
                    "prefab_scripts": prefab_scripts,
                })
        if refs:
            prefab_refs[class_name] = refs

    # 4. Component types referenced (GetComponent + implied by callbacks)
    component_types: set[str] = set()
    for a in analyzed.values():
        component_types.update(a.get("get_component_types", []))
        component_types.update(a.get("implied_components", []))

    # 5. Classes in win/lose condition paths (singleton pattern)
    #    GameManager.instance.GameWin/GameLose callers → trace back singleton_writes
    condition_path_classes: set[str] = set()
    win_callers:  set[str] = set()
    lose_callers: set[str] = set()
    for class_name, a in analyzed.items():
        for sc in a.get("singleton_calls", []):
            if sc["class"] == "GameManager":
                if sc["method"] == "GameWin":
                    win_callers.add(class_name)
                elif sc["method"] == "GameLose":
                    lose_callers.add(class_name)
    for class_name, a in analyzed.items():
        for sw in a.get("singleton_writes", []):
            if sw["class"] in win_callers or sw["class"] in lose_callers:
                condition_path_classes.add(class_name)
    condition_path_classes |= win_callers | lose_callers
    if "GameManager" in analyzed or any(
        sc["class"] == "GameManager"
        for a in analyzed.values()
        for sc in a.get("singleton_calls", [])
    ):
        condition_path_classes.add("GameManager")

    # ── per-script summary (clean, no yaml_fields blob) ───────────────
    scripts_summary: dict[str, dict] = {}
    for class_name, a in analyzed.items():
        entry: dict = {
            "source_file":         a["source_file"],
            "origin":              a.get("origin", "scene"),
            "go_name":             a.get("go_name", ""),
            "callbacks":           a.get("callbacks", []),
            "tags_checked":        a.get("tags_checked", []),
            "singleton_calls":     a.get("singleton_calls", []),
            "singleton_writes":    a.get("singleton_writes", []),
            "get_component_types": a.get("get_component_types", []),
            "implied_components":  a.get("implied_components", []),
            "field_declarations":  [f["name"] for f in a.get("field_declarations", [])],
        }
        if a.get("origin") == "prefab":
            entry["prefab_name"] = a.get("prefab_name", "")
        scripts_summary[class_name] = entry

    return {
        "pattern": pattern,
        "scripts": scripts_summary,
        "demands": {
            "tags":                   sorted(all_tags),
            "inspector_fields":       inspector_fields,
            "prefab_refs":            prefab_refs,
            "component_types":        sorted(component_types),
            "condition_path_classes": sorted(condition_path_classes),
        },
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

    print("Building GUID → class index...")
    guid_to_class = build_guid_to_class(SCRIPTS_DIR)
    print(f"  {len(guid_to_class)} scripts.")

    print("Building GUID → prefab index...")
    guid_to_prefab = build_guid_to_prefab(PREFABS_DIR)
    print(f"  {len(guid_to_prefab)} prefabs.\n")

    ok = 0
    for pattern in patterns:
        result = build_manifest(pattern, guid_to_class, guid_to_prefab)
        if result is None:
            print(f"  SKIP  {pattern} (no _parsed.json)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_manifest.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        n_scripts    = len(result["scripts"])
        n_tags       = len(result["demands"]["tags"])
        n_fields     = sum(len(v) for v in result["demands"]["inspector_fields"].values())
        n_prefabs    = sum(len(v) for v in result["demands"]["prefab_refs"].values())
        n_components = len(result["demands"]["component_types"])
        n_cond       = len(result["demands"]["condition_path_classes"])
        print(f"  {pattern}: {n_scripts} scripts | tags={n_tags} "
              f"fields={n_fields} prefabs={n_prefabs} "
              f"components={n_components} condition_classes={n_cond}")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns.")


if __name__ == "__main__":
    main()
