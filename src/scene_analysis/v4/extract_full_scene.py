#!/usr/bin/env python3
"""
IR V4 — Pass 4: Full Scene Extraction

Extracts ALL GameObjects and their components from _parsed.json,
not just those hosting user scripts. This is the V4 upgrade from
V3's demand-driven scoping.

For prefab-origin GOs (identified by Pass 1 manifest), the prefab
file is also parsed.

Filters:
  - Transform/RectTransform: extracted as GO-level property, not component
  - Scene-level settings: excluded (not GameObjects)

Input:
  data/processed/scene_analysis/<pattern>_parsed.json
  data/processed/scene_analysis/<pattern>_manifest.json

Output:
  data/processed/scene_analysis/<pattern>_full_scene.json

Usage:
    uv run python src/scene_analysis/v4/extract_full_scene.py
    uv run python src/scene_analysis/v4/extract_full_scene.py 1_Ownership
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ASSETS_DIR         = ROOT / "data" / "raw" / "unity" / "PatternsUnityCode" / "Assets"
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
_BLOCK_HEADER_RE = re.compile(r"^--- !u!(\d+) &(\d+)", re.MULTILINE)

TRANSFORM_TYPES = {"Transform", "RectTransform"}
SETTINGS_TYPES  = {"OcclusionCullingSettings", "RenderSettings",
                   "LightmapSettings", "NavMeshSettings"}

# Fields that are project-specific and won't exist in a clean Unity project.
# Non-zero sortingLayerID references a custom sorting layer defined in
# ProjectSettings/TagManager.asset — it causes silent fallback to Default.
NON_PORTABLE_FIELDS = {"m_SortingLayerID"}


# ── GUID index ────────────────────────────────────────────────────────

def build_guid_to_class(scripts_dir: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for meta in scripts_dir.rglob("*.cs.meta"):
        text = meta.read_text(encoding="utf-8")
        m = _GUID_RE.search(text)
        if not m:
            continue
        cs = meta.with_suffix("")
        index[m.group(1)] = {"class_name": cs.stem}
    return index


# ── scene graph ───────────────────────────────────────────────────────

def extract_full_scene(pattern: str, guid_to_class: dict[str, dict]) -> dict | None:
    parsed_path = SCENE_ANALYSIS_DIR / f"{pattern}_parsed.json"
    if not parsed_path.exists():
        return None

    with open(parsed_path, encoding="utf-8") as f:
        parsed = json.load(f)

    # Build GO name map and component-to-GO map
    go_names: dict[str, str] = {}
    go_data_map: dict[str, dict] = {}
    comp_to_go: dict[str, str] = {}
    go_to_comps: dict[str, list[tuple[str, str]]] = {}  # go_fid → [(comp_fid, btype)]
    fid_to_block: dict[str, tuple[str, dict]] = {}  # fid → (btype, data)

    for btype, blocks in parsed["blocksByType"].items():
        if btype in SETTINGS_TYPES:
            continue
        for blk in blocks:
            fid = str(blk["fileID"])
            data = blk["data"].get(btype, {})
            fid_to_block[fid] = (btype, data)

            if btype == "GameObject":
                go_names[fid] = data.get("m_Name", "")
                go_data_map[fid] = data
                go_to_comps.setdefault(fid, [])
            else:
                go_ref = data.get("m_GameObject", {})
                go_fid = str(go_ref.get("fileID", 0)) if isinstance(go_ref, dict) else "0"
                if go_fid and go_fid != "0":
                    comp_to_go[fid] = go_fid
                    go_to_comps.setdefault(go_fid, []).append((fid, btype))

    # Extract all GOs
    scene_gos: dict[str, dict] = {}
    for go_fid, go_name in go_names.items():
        transform_data = None
        components: list[dict] = []

        for comp_fid, btype in go_to_comps.get(go_fid, []):
            _, data = fid_to_block.get(comp_fid, ("", {}))

            if btype in TRANSFORM_TYPES:
                transform_data = {
                    "position": data.get("m_LocalPosition", {"x": 0, "y": 0, "z": 0}),
                    "scale": data.get("m_LocalScale", {"x": 1, "y": 1, "z": 1}),
                    "rotation": data.get("m_LocalRotation", {"x": 0, "y": 0, "z": 0, "w": 1}),
                }
                # Also store children/parent for hierarchy
                children = data.get("m_Children", [])
                father = data.get("m_Father", {})
                if children:
                    transform_data["children_count"] = len(children)
                if isinstance(father, dict) and father.get("fileID", 0) != 0:
                    transform_data["has_parent"] = True
                continue

            # Strip non-portable fields (e.g. project-specific sortingLayerID)
            clean_data = {k: v for k, v in data.items()
                          if k not in NON_PORTABLE_FIELDS or v == 0}

            entry: dict = {"type": btype, "data": clean_data}

            # Resolve MonoBehaviour class name
            if btype == "MonoBehaviour":
                guid = data.get("m_Script", {}).get("guid")
                if guid:
                    cls_info = guid_to_class.get(guid)
                    if cls_info:
                        entry["class_name"] = cls_info["class_name"]

            components.append(entry)

        go_entry: dict = {
            "go_fid": go_fid,
            "components": components,
        }
        if transform_data:
            go_entry["transform"] = transform_data
        if go_data_map.get(go_fid, {}).get("m_TagString", "Untagged") != "Untagged":
            go_entry["tag"] = go_data_map[go_fid]["m_TagString"]
        if go_data_map.get(go_fid, {}).get("m_IsActive", 1) == 0:
            go_entry["active"] = False

        scene_gos[go_name] = go_entry

    # Add prefab GOs from manifest
    manifest_path = SCENE_ANALYSIS_DIR / f"{pattern}_manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        for cls, sinfo in manifest.get("scripts", {}).items():
            if sinfo.get("origin") != "prefab":
                continue
            prefab_name = sinfo.get("prefab_name", "")
            key = f"(prefab) {prefab_name}"
            if key in scene_gos:
                continue
            # Find and parse prefab
            prefab_path = _find_prefab(prefab_name)
            if prefab_path:
                prefab_gos = _parse_prefab_gos(prefab_path, guid_to_class)
                if prefab_gos:
                    scene_gos[key] = {
                        "origin": "prefab",
                        "prefab_name": prefab_name,
                        **prefab_gos,
                    }

    return {
        "pattern": pattern,
        "scene_gos": scene_gos,
    }


def _find_prefab(prefab_name: str) -> Path | None:
    for p in PREFABS_DIR.rglob(f"{prefab_name}.prefab"):
        return p
    return None


def _parse_prefab_gos(prefab_path: Path, guid_to_class: dict[str, dict]) -> dict | None:
    """Parse prefab and return combined component data for the root GO."""
    text = prefab_path.read_text(encoding="utf-8")
    headers = list(_BLOCK_HEADER_RE.finditer(text))

    # Find root GO (first GameObject block)
    root_go_fid = None
    for h in headers:
        if int(h.group(1)) == 1:  # classID 1 = GameObject
            root_go_fid = h.group(2)
            break

    if not root_go_fid:
        return None

    transform_data = None
    components: list[dict] = []

    for i, h in enumerate(headers):
        body_start = h.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end].strip()

        first_key = re.match(r"^(\w+):", body)
        if not first_key:
            continue
        btype = first_key.group(1)

        if btype == "GameObject":
            continue

        # Check if this component belongs to root GO
        gom = re.search(r"m_GameObject:\s*\{fileID:\s*(-?\d+)\}", body)
        if not gom or gom.group(1) != root_go_fid:
            continue

        if btype in TRANSFORM_TYPES:
            pos_m = re.search(r"m_LocalPosition:\s*\{([^}]+)\}", body)
            scale_m = re.search(r"m_LocalScale:\s*\{([^}]+)\}", body)
            rot_m = re.search(r"m_LocalRotation:\s*\{([^}]+)\}", body)
            transform_data = {
                "position": _parse_inline_dict(pos_m.group(1)) if pos_m else {},
                "scale": _parse_inline_dict(scale_m.group(1)) if scale_m else {},
                "rotation": _parse_inline_dict(rot_m.group(1)) if rot_m else {},
            }
            continue

        data = _parse_prefab_block(body, btype)
        entry: dict = {"type": btype, "data": data}

        if btype == "MonoBehaviour":
            sm = re.search(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})", body)
            if sm:
                cls_info = guid_to_class.get(sm.group(1))
                if cls_info:
                    entry["class_name"] = cls_info["class_name"]

        components.append(entry)

    result: dict = {"components": components}
    if transform_data:
        result["transform"] = transform_data
    return result


def _parse_inline_dict(s: str) -> dict:
    result = {}
    for m in re.finditer(r"(\w+):\s*(-?[\d.e+]+)", s):
        try:
            result[m.group(1)] = int(m.group(2))
        except ValueError:
            result[m.group(1)] = float(m.group(2))
    return result


def _parse_prefab_block(text: str, btype: str) -> dict:
    """Lightweight parse of a prefab component block."""
    result: dict = {}
    for m in re.finditer(r"^  (\w+):\s*([^\n{}\[\]]+)$", text, re.MULTILINE):
        k, v = m.group(1), m.group(2).strip()
        try:
            result[k] = int(v)
            continue
        except ValueError:
            pass
        try:
            result[k] = float(v)
            continue
        except ValueError:
            pass
        if v == "null" or v == "":
            result[k] = None
        else:
            result[k] = v
    for m in re.finditer(r"^  (\w+):\s*\{([^}]+)\}", text, re.MULTILINE):
        k = m.group(1)
        if k in ("m_GameObject", "m_Script"):
            continue
        result[k] = _parse_inline_dict(m.group(2))
    return result


# ── main ──────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        patterns = THREE_PATTERNS
    elif args[0] == "--all":
        patterns = ALL_PATTERNS
    else:
        patterns = args

    guid_to_class = build_guid_to_class(ASSETS_DIR / "Scripts")

    ok = 0
    for pattern in patterns:
        result = extract_full_scene(pattern, guid_to_class)
        if result is None:
            print(f"  SKIP  {pattern}")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_full_scene.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        n_gos = len(result["scene_gos"])
        n_comps = sum(len(g.get("components", [])) for g in result["scene_gos"].values())
        n_with_script = sum(
            1 for g in result["scene_gos"].values()
            if any(c.get("class_name") for c in g.get("components", []))
        )
        n_no_script = n_gos - n_with_script
        print(f"  {pattern}: {n_gos} GOs ({n_with_script} scripted, {n_no_script} config-only), {n_comps} components")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns.")


if __name__ == "__main__":
    main()
