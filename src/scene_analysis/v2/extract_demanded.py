#!/usr/bin/env python3
"""
IR V2 — Pass 2: Targeted Scene Extraction

Reads the demand manifest produced by Pass 1 and queries _parsed.json
for exactly the data the scripts reference. No component type is
excluded a priori — if the scripts demand it, it is extracted.

For scene-origin scripts: queries _parsed.json directly.
For prefab-origin scripts: parses the prefab .asset file.

Physics-critical m_ fields (isTrigger, gravityScale, bodyType, etc.)
ARE extracted here — they govern whether callbacks like OnTriggerEnter2D
fire and are therefore gameplay-relevant even though they carry the m_ prefix.

Input:
  data/processed/scene_analysis/<pattern>_parsed.json
  data/processed/scene_analysis/<pattern>_manifest.json

Output:
  data/processed/scene_analysis/<pattern>_extraction.json

Usage:
    uv run python src/scene_analysis/v2/extract_demanded.py
    uv run python src/scene_analysis/v2/extract_demanded.py 1_Ownership
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT               = Path(__file__).resolve().parents[3]
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

_BLOCK_HEADER_RE = re.compile(r"^--- !u!(\d+) &(\d+)", re.MULTILINE)
_GUID_RE         = re.compile(r"^guid:\s*([0-9a-f]{32})", re.MULTILINE)

# Physics-critical m_ fields to extract (not user-named, but gameplay-relevant)
COLLIDER_PHYSICS_FIELDS = {
    "m_Enabled", "m_IsTrigger", "m_Size", "m_Radius", "m_Offset",
    "m_Direction",       # CapsuleCollider2D
    "m_IncludeLayers", "m_ExcludeLayers",
}
RIGIDBODY_PHYSICS_FIELDS = {
    "m_Enabled", "m_BodyType", "m_Mass", "m_GravityScale",
    "m_LinearDamping", "m_AngularDamping", "m_Constraints",
    "m_Simulated",
}
COLLIDER_TYPES    = {"BoxCollider2D", "CircleCollider2D", "PolygonCollider2D",
                     "CapsuleCollider2D", "EdgeCollider2D",
                     "BoxCollider", "SphereCollider", "CapsuleCollider", "MeshCollider"}
RIGIDBODY_TYPES   = {"Rigidbody2D", "Rigidbody"}


# ── prefab parser ─────────────────────────────────────────────────────

def parse_prefab(prefab_path: Path) -> dict[str, list[dict]]:
    """
    Parse a .prefab file into { type_name: [ {fileID, data} ] }
    Same structure as _parsed.json blocksByType.
    """
    if not prefab_path.exists():
        return {}
    text    = prefab_path.read_text(encoding="utf-8")
    headers = list(_BLOCK_HEADER_RE.finditer(text))
    blocks_by_type: dict[str, list[dict]] = {}

    for i, h in enumerate(headers):
        body_start = h.end()
        body_end   = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body_text  = text[body_start:body_end].strip()

        # Parse first YAML key as type name
        first_key = re.match(r"^(\w+):", body_text)
        if not first_key:
            continue
        type_name = first_key.group(1)
        file_id   = int(h.group(2))

        # Lightweight YAML parse: extract key-value pairs one level deep
        data = _lightweight_yaml_parse(body_text, type_name)
        blocks_by_type.setdefault(type_name, []).append({
            "fileID": file_id,
            "data":   {type_name: data},
        })

    return blocks_by_type


def _lightweight_yaml_parse(text: str, root_key: str) -> dict:
    """
    Extract the content under `root_key:` from YAML text using the
    same approach as parse_unity_scene.py — json.loads on the
    already-parsed _parsed.json is not available here, so we re-parse.

    Limitation: nested dicts / lists returned as raw strings for fields
    we don't specifically need. For our purposes (m_GameObject fileID,
    physics fields) a targeted regex approach is more reliable.
    """
    result: dict = {}

    # m_GameObject.fileID
    m = re.search(r"m_GameObject:\s*\{fileID:\s*(-?\d+)\}", text)
    if m:
        result["m_GameObject"] = {"fileID": int(m.group(1))}

    # m_Script.guid
    m = re.search(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})", text)
    if m:
        result["m_Script"] = {"guid": m.group(1)}

    # Scalar fields: key: value (int, float, bool, string — single line)
    for km in re.finditer(r"^  (\w+):\s*([^\n{}\[\]]+)$", text, re.MULTILINE):
        k, v = km.group(1), km.group(2).strip()
        # Try numeric
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
        result[k] = v

    # Inline dict fields: key: {a: x, b: y}
    # Skip m_GameObject and m_Script — already handled above with dedicated regexes
    for km in re.finditer(r"^  (\w+):\s*\{([^}]+)\}", text, re.MULTILINE):
        k = km.group(1)
        if k in ("m_GameObject", "m_Script"):
            continue
        sub = {}
        for pair in re.finditer(r"(\w+):\s*(-?[\d.]+)", km.group(2)):
            try:
                sub[pair.group(1)] = int(pair.group(2))
            except ValueError:
                sub[pair.group(1)] = float(pair.group(2))
        result[k] = sub

    return result


# ── scene graph helpers ───────────────────────────────────────────────

def build_scene_graph(parsed: dict) -> tuple[
    dict[str, str],       # fid → type
    dict[str, str],       # comp_fid → go_fid  (via m_GameObject)
    dict[str, str],       # go_fid → go_name
    dict[str, list[str]], # go_fid → [comp_fids of each type]
]:
    fid_to_type:   dict[str, str]        = {}
    comp_to_go:    dict[str, str]        = {}
    go_names:      dict[str, str]        = {}
    go_to_comps:   dict[str, list[str]]  = {}

    for btype, blocks in parsed["blocksByType"].items():
        for blk in blocks:
            fid = str(blk["fileID"])
            fid_to_type[fid] = btype
            data = blk["data"].get(btype, {})

            if btype == "GameObject":
                go_names[fid] = data.get("m_Name", "")
                go_to_comps.setdefault(fid, [])
            else:
                go_ref = data.get("m_GameObject", {})
                go_fid = str(go_ref.get("fileID", 0)) if isinstance(go_ref, dict) else "0"
                if go_fid and go_fid != "0":
                    comp_to_go[fid] = go_fid
                    go_to_comps.setdefault(go_fid, []).append(fid)

    return fid_to_type, comp_to_go, go_names, go_to_comps


def extract_physics_fields(data: dict, physics_fields: set[str]) -> dict:
    """Extract only the physics-critical fields from a component's data dict."""
    return {k: v for k, v in data.items() if k in physics_fields}


# ── demand resolution ─────────────────────────────────────────────────

def resolve_tags(parsed: dict, demanded_tags: list[str]) -> dict[str, list[dict]]:
    """Find GOs that have each demanded tag. Also collect all non-Untagged tags."""
    result: dict[str, list[dict]] = {}
    for blk in parsed["blocksByType"].get("GameObject", []):
        go_data = blk["data"].get("GameObject", {})
        tag     = go_data.get("m_TagString", "")
        if tag and tag != "Untagged":
            result.setdefault(tag, []).append({
                "go_fid":  str(blk["fileID"]),
                "go_name": go_data.get("m_Name", ""),
            })
    # Filter to only demanded tags (but keep all found for reference)
    if demanded_tags:
        return {t: v for t, v in result.items() if t in demanded_tags or not demanded_tags}
    return result


def resolve_inspector_fields(
    parsed: dict,
    demanded: dict[str, list[str]],   # class_name → [field_names]
    guid_to_class: dict[str, dict],
    go_names: dict[str, str],
    comp_to_go: dict[str, str],
) -> dict[str, dict]:
    """
    For each demanded class, find its MB in the scene and extract
    only the demanded field values.
    """
    result: dict[str, dict] = {}
    for blk in parsed["blocksByType"].get("MonoBehaviour", []):
        mb_fid  = str(blk["fileID"])
        mb_data = blk["data"].get("MonoBehaviour", {})
        guid    = mb_data.get("m_Script", {}).get("guid")
        if not guid:
            continue
        class_name = guid_to_class.get(guid, {}).get("class_name")
        if not class_name or class_name not in demanded:
            continue
        go_fid  = comp_to_go.get(mb_fid, "")
        fields  = demanded[class_name]
        values  = {f: mb_data[f] for f in fields if f in mb_data}
        result[class_name] = {
            "go_name": go_names.get(go_fid, ""),
            "go_fid":  go_fid,
            "fields":  values,
        }
    return result


def resolve_component_data(
    parsed: dict,
    manifest_scripts: dict,
    comp_to_go: dict[str, str],
    go_to_comps: dict[str, list[str]],
    fid_to_type: dict[str, str],
    go_names: dict[str, str],
    guid_to_class: dict[str, dict],
    guid_to_prefab: dict[str, dict],
) -> dict[str, dict]:
    """
    For scripts with implied_components (OnTrigger*, OnCollision*) or
    GetComponent calls, find and extract the relevant component data.

    Scene-origin: queries _parsed.json.
    Prefab-origin: parses the prefab file.
    """
    # Build class_name → mb_fid for scene scripts
    class_to_mb: dict[str, str] = {}
    for blk in parsed["blocksByType"].get("MonoBehaviour", []):
        mb_data = blk["data"].get("MonoBehaviour", {})
        guid    = mb_data.get("m_Script", {}).get("guid")
        if not guid:
            continue
        cn = guid_to_class.get(guid, {}).get("class_name")
        if cn:
            class_to_mb[cn] = str(blk["fileID"])

    result: dict[str, dict] = {}

    for class_name, sinfo in manifest_scripts.items():
        implied  = sinfo.get("implied_components", [])
        gc_types = sinfo.get("get_component_types", [])
        if not implied and not gc_types:
            continue

        entry: dict = {
            "origin":     sinfo.get("origin", "scene"),
            "implied_by": [c for c in implied],
            "colliders":  [],
            "rigidbodies": [],
            "other_components": [],
        }

        if sinfo.get("origin") == "scene":
            mb_fid = class_to_mb.get(class_name)
            go_fid = comp_to_go.get(mb_fid, "") if mb_fid else ""
            entry["go_name"] = go_names.get(go_fid, "")

            # Find all components on the same GO
            sibling_fids = go_to_comps.get(go_fid, [])
            for sfid in sibling_fids:
                btype = fid_to_type.get(sfid)
                if not btype or btype == "MonoBehaviour":
                    continue
                # Find the block
                for blk in parsed["blocksByType"].get(btype, []):
                    if str(blk["fileID"]) != sfid:
                        continue
                    bdata = blk["data"].get(btype, {})
                    if btype in COLLIDER_TYPES:
                        entry["colliders"].append({
                            "type":   btype,
                            **extract_physics_fields(bdata, COLLIDER_PHYSICS_FIELDS),
                        })
                    elif btype in RIGIDBODY_TYPES:
                        entry["rigidbodies"].append({
                            "type":   btype,
                            **extract_physics_fields(bdata, RIGIDBODY_PHYSICS_FIELDS),
                        })
                    elif btype in (gc_types or []):
                        entry["other_components"].append({
                            "type":  btype,
                            "fields": {k: v for k, v in bdata.items()
                                       if not k.startswith("m_")},
                        })

        else:  # prefab-origin
            prefab_name = sinfo.get("prefab_name", "")
            entry["go_name"] = f"(prefab) {prefab_name}"
            # Find prefab path from guid_to_prefab by name
            prefab_path = None
            for pinfo in guid_to_prefab.values():
                if pinfo["prefab_name"] == prefab_name:
                    prefab_path = ROOT / pinfo["prefab_path"]
                    break
            if prefab_path:
                pfab_blocks = parse_prefab(prefab_path)
                # Find the MB for this class, then find sibling components on same GO
                mb_go_fid = None
                for blk in pfab_blocks.get("MonoBehaviour", []):
                    bdata = blk["data"].get("MonoBehaviour", {})
                    guid  = bdata.get("m_Script", {}).get("guid")
                    if not guid:
                        continue
                    if guid_to_class.get(guid, {}).get("class_name") == class_name:
                        mb_go_fid = str(bdata.get("m_GameObject", {}).get("fileID", 0))
                        break

                if mb_go_fid:
                    for btype, blocks in pfab_blocks.items():
                        if btype in ("MonoBehaviour", "GameObject"):
                            continue
                        for blk in blocks:
                            bdata  = blk["data"].get(btype, {})
                            go_ref = bdata.get("m_GameObject", {})
                            if isinstance(go_ref, dict) and str(go_ref.get("fileID", 0)) == mb_go_fid:
                                if btype in COLLIDER_TYPES:
                                    entry["colliders"].append({
                                        "type": btype,
                                        **extract_physics_fields(bdata, COLLIDER_PHYSICS_FIELDS),
                                    })
                                elif btype in RIGIDBODY_TYPES:
                                    entry["rigidbodies"].append({
                                        "type": btype,
                                        **extract_physics_fields(bdata, RIGIDBODY_PHYSICS_FIELDS),
                                    })
                                elif btype in gc_types:
                                    entry["other_components"].append({
                                        "type": btype,
                                    })

        result[class_name] = entry

    return result


# ── per-pattern extraction ────────────────────────────────────────────

def extract_pattern(
    pattern: str,
    guid_to_class: dict[str, dict],
    guid_to_prefab: dict[str, dict],
) -> dict | None:
    parsed_path   = SCENE_ANALYSIS_DIR / f"{pattern}_parsed.json"
    manifest_path = SCENE_ANALYSIS_DIR / f"{pattern}_manifest.json"
    if not parsed_path.exists() or not manifest_path.exists():
        return None

    with open(parsed_path,   encoding="utf-8") as f:
        parsed   = json.load(f)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    fid_to_type, comp_to_go, go_names, go_to_comps = build_scene_graph(parsed)
    demands  = manifest["demands"]
    scripts  = manifest["scripts"]

    tags_found = resolve_tags(parsed, demands.get("tags", []))

    inspector_values = resolve_inspector_fields(
        parsed,
        demands.get("inspector_fields", {}),
        guid_to_class,
        go_names,
        comp_to_go,
    )

    component_data = resolve_component_data(
        parsed, scripts, comp_to_go, go_to_comps,
        fid_to_type, go_names, guid_to_class, guid_to_prefab,
    )

    return {
        "pattern":         pattern,
        "tags_found":      tags_found,
        "inspector_values": inspector_values,
        "prefab_refs":     demands.get("prefab_refs", {}),
        "component_data":  component_data,
        "condition_path_classes": demands.get("condition_path_classes", []),
    }


# ── GUID indexes (same logic as Pass 1) ──────────────────────────────

def build_guid_to_class(scripts_dir: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for meta in scripts_dir.rglob("*.cs.meta"):
        text = meta.read_text(encoding="utf-8")
        m    = _GUID_RE.search(text)
        if not m:
            continue
        cs = meta.with_suffix("")
        index[m.group(1)] = {
            "class_name":  cs.stem,
            "source_file": str(cs.relative_to(ROOT)),
        }
    return index


def build_guid_to_prefab(prefabs_dir: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for meta in prefabs_dir.rglob("*.prefab.meta"):
        text = meta.read_text(encoding="utf-8")
        m    = _GUID_RE.search(text)
        if not m:
            continue
        prefab = meta.with_suffix("")
        index[m.group(1)] = {
            "prefab_name": prefab.stem,
            "prefab_path": str(prefab.relative_to(ROOT)),
        }
    return index


# ── main ──────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        patterns = THREE_PATTERNS
    elif args[0] == "--all":
        patterns = ALL_PATTERNS
    else:
        patterns = args

    scripts_dir = ASSETS_DIR / "Scripts"
    guid_to_class  = build_guid_to_class(scripts_dir)
    guid_to_prefab = build_guid_to_prefab(PREFABS_DIR)

    ok = 0
    for pattern in patterns:
        result = extract_pattern(pattern, guid_to_class, guid_to_prefab)
        if result is None:
            print(f"  SKIP  {pattern} (missing _parsed.json or _manifest.json)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_extraction.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        n_tags  = len(result["tags_found"])
        n_insp  = sum(len(v["fields"]) for v in result["inspector_values"].values())
        n_comp  = len(result["component_data"])
        n_pfab  = sum(len(v) for v in result["prefab_refs"].values())
        print(f"  {pattern}: tags={n_tags} inspector_fields={n_insp} "
              f"components={n_comp} prefab_refs={n_pfab}")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns.")


if __name__ == "__main__":
    main()
