#!/usr/bin/env python3
"""
Stage 3: Inspector value extraction.

Reads the raw YAML data (from _parsed.json) and applies two technically-
determined filtering rules to extract quantified configuration for each MB:
  - inspector_scalars: numeric/bool/string/vector fields
  - inspector_refs:    object reference fields, classified by target type
  - enabled:          whether the MB is active (exception to m_ rule)
  - go_tags:          GO tags used by scripts for runtime lookup

Both filtering rules are technically determined, not content judgments:
  Rule 1 — m_ prefix: Unity's own naming convention for internal fields.
           Any researcher applying this rule to this data gets the same result.
  Rule 2 — null ref:  {fileID: 0, no guid} is Unity's sentinel for null.
           Drops no information — a null ref points to nothing.

The original data remains in _parsed.json. Nothing is discarded permanently.

Input:
  data/processed/scene_analysis/<N>_<PatternName>_parsed.json
  data/processed/scene_analysis/<N>_<PatternName>_identity.json  (for class_name/go_name)
  data/processed/scene_analysis/<N>_<PatternName>_links.json     (for ref classification)
  data/processed/scene_analysis/prefab_guid_index.json
  data/processed/scene_analysis/guid_to_asset.json

Output:
  data/processed/scene_analysis/<N>_<PatternName>_inspector.json
    {
      "scene": "1_Ownership",
      "monobehaviours": {
        "<mb_fileID>": {
          "class_name":       "SpawnManager",
          "go_name":          "Spawn Manager",
          "enabled":          true,
          "inspector_scalars": { "spawnCount": 8, "spawnRangeX": 8.5, ... },
          "inspector_refs":   [
            {
              "field":        "spawnPrefab",
              "fileID":       4452553723177078481,
              "guid":         "057536c2...",
              "target_type":  "to_prefab_id",
              "to_prefab_id": "OwnershipObject"
            }
          ]
        }
      },
      "go_tags": { "<go_fileID>": "Player", ... }
    }

Usage:
    uv run python src/scene_analysis/extract_inspector.py            # all patterns
    uv run python src/scene_analysis/extract_inspector.py 1_Ownership
"""

from __future__ import annotations

import json
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


# ── Step 3.1 — Inspector field extraction ────────────────────────────

def extract_inspector_fields(mb_data: dict) -> tuple[dict, list[dict]]:
    """
    Extract Inspector fields from a MonoBehaviour data dict.

    Rule 1 — skip m_ prefix fields (technically determined):
      Unity uses m_ for all internal serialized fields. This is a Unity
      naming convention, not a gameplay judgment. User-defined public /
      [SerializeField] fields never use this prefix.
      Exception: m_Enabled is extracted separately (see below).

    Rule 2 — skip null object references (technically determined):
      {fileID: 0} with no guid is Unity's serialization sentinel for null.
      It points to nothing and carries no information.
      Only applied to dicts that contain a fileID key (object refs).
      Non-reference dicts (Vector3, Color, etc.) are kept as scalars.

    Returns:
      scalars — { field: value } for numeric/bool/string/vector fields
      refs    — [ { field, fileID, guid } ] for non-null object references
    """
    scalars: dict = {}
    refs: list[dict] = []

    for field, value in mb_data.items():
        # Rule 1: skip Unity-internal fields
        if field.startswith("m_"):
            continue

        if isinstance(value, dict):
            if "fileID" in value:
                # Object reference — apply Rule 2
                file_id = value.get("fileID", 0)
                guid    = value.get("guid")
                if file_id == 0 and not guid:
                    continue   # null reference
                refs.append({"field": field, "fileID": file_id, "guid": guid})
            else:
                # Non-reference dict (Vector2, Vector3, Color, etc.) — keep as scalar
                scalars[field] = value
        else:
            scalars[field] = value

    return scalars, refs


# ── Step 3.2 — Inspector ref classification ───────────────────────────

def classify_inspector_refs(
    refs: list[dict],
    go_names: dict[str, str],
    comp_to_go: dict[str, str],
    prefab_index: dict[str, dict],
    asset_index: dict[str, dict],
) -> list[dict]:
    """
    Classify each inspector_ref by target type:

      to_prefab_id  — guid resolves to a known prefab asset
      to_go_id      — fileID points to a GO or a component whose parent GO is known
      to_asset_guid — guid present but not a prefab; asset_type and asset_path
                      added from guid_to_asset.json so the reference is typed
      unresolved    — no guid, fileID not in any known map
    """
    result = []
    for ref in refs:
        entry   = dict(ref)
        file_id = str(ref.get("fileID", 0))
        guid    = ref.get("guid")

        if guid and guid in prefab_index:
            entry["target_type"]   = "to_prefab_id"
            entry["to_prefab_id"]  = prefab_index[guid]["prefab_name"]
        elif file_id and file_id != "0" and file_id in go_names:
            entry["target_type"] = "to_go_id"
            entry["to_go_id"]    = file_id
        elif file_id and file_id != "0" and file_id in comp_to_go:
            go_id = comp_to_go[file_id]
            entry["target_type"] = "to_go_id"
            entry["to_go_id"]    = go_id
        elif guid:
            # Asset reference — record type from full asset index (lossless)
            asset_info = asset_index.get(guid, {})
            entry["target_type"]   = "to_asset_guid"
            entry["to_asset_guid"] = guid
            entry["asset_type"]    = asset_info.get("asset_type", "Unknown")
            entry["asset_path"]    = asset_info.get("asset_path")
        else:
            entry["target_type"] = "unresolved"

        result.append(entry)
    return result


# ── Step 3.3 — GO tag extraction ──────────────────────────────────────

def extract_go_tags(parsed: dict) -> dict[str, str]:
    """
    Read m_TagString from every GameObject block.
    Return { go_fileID: tag } for all GOs whose tag is not "Untagged".
    "Untagged" is Unity's default — carries no information by definition.
    """
    tags: dict[str, str] = {}
    for block in parsed.get("blocksByType", {}).get("GameObject", []):
        go_data = block["data"].get("GameObject", {})
        tag = go_data.get("m_TagString", "")
        if tag and tag != "Untagged":
            tags[str(block["fileID"])] = tag
    return tags


# ── per-pattern extraction ────────────────────────────────────────────

def extract_pattern(
    pattern: str,
    prefab_index: dict[str, dict],
    asset_index: dict[str, dict],
) -> dict | None:
    parsed_path   = SCENE_ANALYSIS_DIR / f"{pattern}_parsed.json"
    links_path    = SCENE_ANALYSIS_DIR / f"{pattern}_links.json"
    identity_path = SCENE_ANALYSIS_DIR / f"{pattern}_identity.json"

    if not parsed_path.exists():
        return None

    with open(parsed_path, encoding="utf-8") as f:
        parsed = json.load(f)
    links: dict = {}
    if links_path.exists():
        with open(links_path, encoding="utf-8") as f:
            links = json.load(f)
    identity: dict = {}
    if identity_path.exists():
        with open(identity_path, encoding="utf-8") as f:
            identity = json.load(f)

    comp_to_go: dict[str, str] = links.get("links", {}).get("component_to_gameObject", {})
    go_names:   dict[str, str] = links.get("links", {}).get("gameObject_name", {})
    id_mbs:     dict[str, dict] = identity.get("monobehaviours", {})

    monobehaviours: dict[str, dict] = {}
    for block in parsed.get("blocksByType", {}).get("MonoBehaviour", []):
        mb_fid  = str(block["fileID"])
        mb_data = block["data"].get("MonoBehaviour", {})
        id_entry = id_mbs.get(mb_fid, {})

        scalars, refs = extract_inspector_fields(mb_data)
        classified_refs = classify_inspector_refs(
            refs, go_names, comp_to_go, prefab_index, asset_index
        )

        monobehaviours[mb_fid] = {
            "class_name":       id_entry.get("class_name"),
            "go_name":          id_entry.get("go_name"),
            "enabled":          bool(mb_data.get("m_Enabled", 1)),
            "inspector_scalars": scalars,
            "inspector_refs":   classified_refs,
        }

    return {
        "scene":          pattern,
        "monobehaviours": monobehaviours,
        "go_tags":        extract_go_tags(parsed),
    }


# ── main ──────────────────────────────────────────────────────────────

def main():
    patterns = sys.argv[1:] if len(sys.argv) > 1 else ALL_PATTERNS

    prefab_index_path = SCENE_ANALYSIS_DIR / "prefab_guid_index.json"
    asset_index_path  = SCENE_ANALYSIS_DIR / "guid_to_asset.json"

    if not prefab_index_path.exists() or not asset_index_path.exists():
        print("ERROR: shared indexes not found. Run build_identity.py first.")
        sys.exit(1)

    with open(prefab_index_path, encoding="utf-8") as f:
        prefab_index = json.load(f)
    with open(asset_index_path, encoding="utf-8") as f:
        asset_index = json.load(f)

    ok = 0
    for pattern in patterns:
        result = extract_pattern(pattern, prefab_index, asset_index)
        if result is None:
            print(f"  SKIP  {pattern} (no _parsed.json)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_inspector.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        n_mbs  = len(result["monobehaviours"])
        n_tags = len(result["go_tags"])
        n_refs = sum(
            len(mb["inspector_refs"]) for mb in result["monobehaviours"].values()
        )
        print(f"    {pattern}: {n_mbs} MBs, {n_refs} inspector refs, {n_tags} tags")
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns.")


if __name__ == "__main__":
    main()
