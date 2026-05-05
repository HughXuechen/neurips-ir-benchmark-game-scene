#!/usr/bin/env python3
"""
Stage 2 automation: build GUID indexes, annotate scene MonoBehaviours, and
resolve prefab asset references.

Produces three outputs:

  data/processed/scene_analysis/guid_to_class.json   (shared)
    { "<script_guid>": { "class_name": "...", "source_file": "..." } }

  data/processed/scene_analysis/prefab_guid_index.json   (shared)
    { "<prefab_asset_guid>": { "prefab_name": "...", "prefab_path": "..." } }

  data/processed/scene_analysis/<pattern>_scripts.json   (per pattern)
    {
      "scene": "1_Ownership",
      "monobehaviours": {
        "<mb_fileID>": {
          "go_id": "<parent GO fileID>",
          "go_name": "<GO name>",
          "guid": "<m_Script.guid>",
          "class_name": "<ClassName or null if not in index>",
          "source_file": "<relative path to .cs file or null>"
        }
      },
      "prefab_refs": [
        {
          "from_mb": "<scene MB fileID>",
          "from_class": "<class name of the referencing script>",
          "field": "<Inspector field name>",
          "prefab_guid": "<asset guid>",
          "prefab_name": "<prefab filename without .prefab>",
          "prefab_path": "<relative path to .prefab file>",
          "prefab_monobehaviours": {
            "<prefab MB fileID>": {
              "guid": "<m_Script.guid>",
              "class_name": "<ClassName or null>",
              "source_file": "<relative path to .cs file or null>"
            }
          }
        }
      ]
    }

Usage:
    uv run python src/scene_analysis/build_script_index.py            # all patterns
    uv run python src/scene_analysis/build_script_index.py 1_Ownership
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR   = ROOT / "data" / "raw" / "unity" / "PatternsUnityCode" / "Assets"
SCRIPTS_DIR  = ASSETS_DIR / "Scripts"
PREFABS_DIR  = ASSETS_DIR / "Prefabs"
SCENE_ANALYSIS_DIR = ROOT / "data" / "processed" / "scene_analysis"

# File extension → Unity asset type label
# Used to enrich to_asset_guid entries so all asset references are typed,
# even when the asset is not further parsed (sprites, audio, etc.).
_EXT_TO_ASSET_TYPE: dict[str, str] = {
    ".cs":                    "MonoScript",
    ".prefab":                "Prefab",
    ".unity":                 "Scene",
    ".png":                   "Texture2D",
    ".jpg":                   "Texture2D",
    ".jpeg":                  "Texture2D",
    ".tga":                   "Texture2D",
    ".bmp":                   "Texture2D",
    ".gif":                   "Texture2D",
    ".psd":                   "Texture2D",
    ".mat":                   "Material",
    ".physicsmaterial2d":     "PhysicsMaterial2D",
    ".physicsmaterial":       "PhysicsMaterial",
    ".asset":                 "ScriptableObject",
    ".controller":            "AnimatorController",
    ".overridecontroller":    "AnimatorOverrideController",
    ".anim":                  "AnimationClip",
    ".mask":                  "AvatarMask",
    ".wav":                   "AudioClip",
    ".mp3":                   "AudioClip",
    ".ogg":                   "AudioClip",
    ".aiff":                  "AudioClip",
    ".mixer":                 "AudioMixer",
    ".ttf":                   "Font",
    ".otf":                   "Font",
    ".fontsettings":          "Font",
    ".shader":                "Shader",
    ".hlsl":                  "Shader",
    ".cginc":                 "Shader",
    ".txt":                   "TextAsset",
    ".json":                  "TextAsset",
    ".xml":                   "TextAsset",
    ".bytes":                 "TextAsset",
    ".md":                    "TextAsset",
    ".dll":                   "Plugin",
    ".so":                    "Plugin",
    ".spriteatlas":           "SpriteAtlas",
    ".rendertexture":         "RenderTexture",
    ".cubemap":               "Cubemap",
    ".flare":                 "Flare",
    ".guiskin":               "GUISkin",
}

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

# GUID pattern (32 hex chars)
_GUID_RE = re.compile(r"^guid:\s*([0-9a-f]{32})", re.MULTILINE)
# Unity block header: --- !u!<classID> &<fileID>
_BLOCK_HEADER_RE = re.compile(r"^--- !u!(\d+) &(\d+)", re.MULTILINE)


# ── GUID indexes ──────────────────────────────────────────────────────

def build_asset_guid_index(assets_dir: Path) -> dict[str, dict]:
    """
    Walk ALL .meta files under assets_dir (lossless pass).
    Return { guid: { "asset_type": str, "asset_path": str } } for every
    non-folder asset.  asset_type is derived from the file extension using
    _EXT_TO_ASSET_TYPE; unknown extensions are labelled "Unknown".

    This index is written to guid_to_asset.json and used to annotate
    to_asset_guid inspector_ref entries with a human-readable type,
    so that all asset references in _scripts.json are typed even when
    the asset itself is not further parsed.
    """
    index: dict[str, dict] = {}
    for meta_path in assets_dir.rglob("*.meta"):
        text = meta_path.read_text(encoding="utf-8", errors="replace")

        # Skip folder assets
        if "folderAsset: yes" in text:
            continue

        m = _GUID_RE.search(text)
        if not m:
            continue
        guid = m.group(1)

        # Original asset path = meta path without .meta suffix
        asset_path = meta_path.with_suffix("")
        suffix = asset_path.suffix.lower()
        asset_type = _EXT_TO_ASSET_TYPE.get(suffix, "Unknown")

        index[guid] = {
            "asset_type": asset_type,
            "asset_path": str(asset_path.relative_to(assets_dir.parent)),
        }
    return index


def build_script_guid_index(scripts_dir: Path) -> dict[str, dict]:
    """
    Walk all .cs.meta files under scripts_dir.
    Return { script_guid: { "class_name": str, "source_file": str } }.
    Covers Assets/Scripts/**/*.cs only — not prefab-internal scripts.
    """
    index: dict[str, dict] = {}
    for meta_path in scripts_dir.rglob("*.cs.meta"):
        text = meta_path.read_text(encoding="utf-8")
        m = _GUID_RE.search(text)
        if not m:
            continue
        guid = m.group(1)
        cs_path = meta_path.with_suffix("")        # strip .meta → .cs path
        class_name = cs_path.stem
        source_file = str(cs_path.relative_to(ROOT))
        index[guid] = {"class_name": class_name, "source_file": source_file}
    return index


def build_prefab_guid_index(prefabs_dir: Path) -> dict[str, dict]:
    """
    Walk all .prefab.meta files under prefabs_dir.
    Return { prefab_asset_guid: { "prefab_name": str, "prefab_path": str } }.
    """
    index: dict[str, dict] = {}
    for meta_path in prefabs_dir.rglob("*.prefab.meta"):
        text = meta_path.read_text(encoding="utf-8")
        m = _GUID_RE.search(text)
        if not m:
            continue
        guid = m.group(1)
        prefab_path = meta_path.with_suffix("")    # strip .meta → .prefab path
        prefab_name = prefab_path.stem
        index[guid] = {
            "prefab_name": prefab_name,
            "prefab_path": str(prefab_path.relative_to(ROOT)),
        }
    return index


# ── prefab content parser ─────────────────────────────────────────────

def parse_prefab_monobehaviours(prefab_path: Path,
                                script_index: dict[str, dict]) -> dict[str, dict]:
    """
    Parse a .prefab file and return all MonoBehaviour blocks with resolved
    class names.
    Return { mb_fileID: { "guid": str, "class_name": str|None, "source_file": str|None } }.
    """
    text = prefab_path.read_text(encoding="utf-8")
    result: dict[str, dict] = {}

    # Split into blocks at --- !u!<classID> &<fileID> headers
    headers = list(_BLOCK_HEADER_RE.finditer(text))
    for i, header in enumerate(headers):
        class_id = int(header.group(1))
        file_id  = header.group(2)

        # 114 = MonoBehaviour
        if class_id != 114:
            continue

        # Extract block body (up to next header or EOF)
        body_start = header.end()
        body_end   = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body       = text[body_start:body_end]

        # Extract m_Script.guid from the block body
        script_m = re.search(
            r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})", body
        )
        if not script_m:
            continue
        guid = script_m.group(1)
        resolved = script_index.get(guid, {})
        result[file_id] = {
            "guid":        guid,
            "class_name":  resolved.get("class_name"),
            "source_file": resolved.get("source_file"),
        }

    return result


# ── inspector value extraction ────────────────────────────────────────

def extract_inspector_fields(mb_data: dict) -> tuple[dict, list[dict]]:
    """
    Extract gameplay-relevant Inspector fields from a MonoBehaviour data dict.

    Two filtering rules:
      1. Skip all fields whose name starts with 'm_'.
         Reason: Unity engine uses the 'm_' prefix for all internal serialized
         fields (m_GameObject, m_Script, m_Enabled, etc.). User-defined
         public / [SerializeField] fields never use this prefix.
      2. Skip object-reference fields whose fileID == 0 and have no guid.
         Reason: {fileID: 0} is Unity's null reference — it points to nothing
         and carries no information.

    Returns:
      scalars  — { field: value }  for int/float/bool/string fields
      refs     — [ { field, fileID, guid } ]  for non-null object references
    """
    scalars: dict = {}
    refs: list[dict] = []

    for field, value in mb_data.items():
        # Rule 1: skip Unity-internal fields
        if field.startswith("m_"):
            continue

        if isinstance(value, dict):
            if "fileID" in value:
                # It's a Unity object reference (scene object or asset)
                file_id = value.get("fileID", 0)
                guid    = value.get("guid")
                # Rule 2: skip null references ({fileID: 0} with no guid)
                if file_id == 0 and not guid:
                    continue
                refs.append({"field": field, "fileID": file_id, "guid": guid})
            else:
                # It's a non-reference dict (Vector2, Vector3, Color, etc.) — keep as scalar
                scalars[field] = value
        else:
            scalars[field] = value

    return scalars, refs


# ── inspector ref classification (Stage 3.2) ─────────────────────────

def classify_inspector_refs(
    refs: list[dict],
    go_names: dict[str, str],
    comp_to_go: dict[str, str],
    prefab_index: dict[str, dict],
    asset_index: dict[str, dict],
) -> list[dict]:
    """
    Classify each inspector_ref entry into one of three target types:

      to_go_id      — fileID points directly to a GO, or to a component
                      whose parent GO is in go_names
      to_prefab_id  — guid resolves to a known prefab asset
      to_asset_guid — guid present but not a known prefab (sprite, audio, etc.)
                      asset_type is added from asset_index for all such entries,
                      so every asset reference is typed even when not parsed further

    Returns enriched list with a 'target_type' and resolved target field added.
    """
    result = []
    for ref in refs:
        entry = dict(ref)  # copy
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
            # Asset reference — record type from asset_index (lossless)
            asset_info = asset_index.get(guid, {})
            entry["target_type"]  = "to_asset_guid"
            entry["to_asset_guid"] = guid
            entry["asset_type"]   = asset_info.get("asset_type", "Unknown")
            entry["asset_path"]   = asset_info.get("asset_path")
        else:
            entry["target_type"] = "unresolved"

        result.append(entry)
    return result


# ── GO tag extraction (Stage 3.3) ─────────────────────────────────────

def extract_go_tags(parsed: dict) -> dict[str, str]:
    """
    Read m_TagString from every GameObject block.
    Return { go_fileID: tag } for all GOs whose tag is not 'Untagged'.
    """
    tags: dict[str, str] = {}
    for block in parsed.get("blocksByType", {}).get("GameObject", []):
        go_data = block["data"].get("GameObject", {})
        tag = go_data.get("m_TagString", "")
        if tag and tag != "Untagged":
            tags[str(block["fileID"])] = tag
    return tags


# ── scene MB annotation ───────────────────────────────────────────────

def _extract_asset_guid_fields(mb_data: dict) -> list[tuple[str, str]]:
    """
    Scan a MonoBehaviour's data dict for fields whose value is a Unity
    object reference containing a non-zero guid (i.e., an asset reference).
    Returns list of (field_name, guid_string).
    """
    hits: list[tuple[str, str]] = []
    for field, value in mb_data.items():
        # Skip Unity-internal metadata fields
        if field.startswith("m_"):
            continue
        if isinstance(value, dict):
            guid = value.get("guid")
            if guid and isinstance(guid, str) and len(guid) == 32:
                hits.append((field, guid))
    return hits


def annotate_pattern(
    pattern: str,
    script_index: dict[str, dict],
    prefab_index: dict[str, dict],
    asset_index: dict[str, dict],
) -> dict | None:
    """
    Load <pattern>_parsed.json and <pattern>_links.json.
    Annotate scene MBs with class names and resolve any prefab asset refs.
    Return the full _scripts.json payload, or None if parsed.json missing.
    """
    parsed_path = SCENE_ANALYSIS_DIR / f"{pattern}_parsed.json"
    links_path  = SCENE_ANALYSIS_DIR / f"{pattern}_links.json"

    if not parsed_path.exists():
        return None

    with open(parsed_path, encoding="utf-8") as f:
        parsed = json.load(f)
    links: dict = {}
    if links_path.exists():
        with open(links_path, encoding="utf-8") as f:
            links = json.load(f)

    comp_to_go: dict[str, str] = links.get("links", {}).get("component_to_gameObject", {})
    go_names:   dict[str, str] = links.get("links", {}).get("gameObject_name", {})

    # ── scene monobehaviours ──
    monobehaviours: dict[str, dict] = {}
    for block in parsed.get("blocksByType", {}).get("MonoBehaviour", []):
        mb_fid   = str(block["fileID"])
        mb_data  = block["data"].get("MonoBehaviour", {})
        guid     = mb_data.get("m_Script", {}).get("guid")

        go_id    = comp_to_go.get(mb_fid)
        go_name  = go_names.get(go_id, "") if go_id else ""
        resolved = script_index.get(guid, {}) if guid else {}

        scalars, refs = extract_inspector_fields(mb_data)
        classified_refs = classify_inspector_refs(refs, go_names, comp_to_go, prefab_index, asset_index)
        monobehaviours[mb_fid] = {
            "go_id":               go_id,
            "go_name":             go_name,
            "guid":                guid,
            "class_name":          resolved.get("class_name"),
            "source_file":         resolved.get("source_file"),
            "enabled":             bool(mb_data.get("m_Enabled", 1)),
            "inspector_scalars":   scalars,
            "inspector_refs":      classified_refs,
        }

    # ── prefab asset references ──
    prefab_refs: list[dict] = []
    seen_prefab_guids: set[str] = set()   # deduplicate if same prefab referenced multiple times

    for block in parsed.get("blocksByType", {}).get("MonoBehaviour", []):
        mb_fid      = str(block["fileID"])
        mb_data     = block["data"].get("MonoBehaviour", {})
        from_class  = monobehaviours.get(mb_fid, {}).get("class_name")

        for field, asset_guid in _extract_asset_guid_fields(mb_data):
            if asset_guid not in prefab_index:
                # Not a prefab — do not expand further.
                # This is a technical decision, not a gameplay relevance filter:
                # prefab files (.prefab) contain MonoBehaviour blocks with their
                # own m_Script GUIDs, so they have internal structure that can be
                # parsed into class names and inspector values.
                # Other asset types (Texture2D, AudioClip, Material, etc.) do not
                # contain MonoBehaviour blocks — there is nothing to expand.
                # Their identity is already recorded in inspector_refs via
                # asset_type/asset_path from guid_to_asset.json.
                continue

            prefab_info = prefab_index[asset_guid]
            prefab_path = ROOT / prefab_info["prefab_path"]

            prefab_mbs: dict[str, dict] = {}
            if prefab_path.exists():
                prefab_mbs = parse_prefab_monobehaviours(prefab_path, script_index)

            entry = {
                "from_mb":              mb_fid,
                "from_class":           from_class,
                "field":                field,
                "prefab_guid":          asset_guid,
                "prefab_name":          prefab_info["prefab_name"],
                "prefab_path":          prefab_info["prefab_path"],
                "prefab_monobehaviours": prefab_mbs,
            }
            prefab_refs.append(entry)

            if asset_guid not in seen_prefab_guids:
                seen_prefab_guids.add(asset_guid)

    # ── GO tags (Stage 3.3) ──
    go_tags = extract_go_tags(parsed)

    return {
        "scene":          pattern,
        "monobehaviours": monobehaviours,
        "prefab_refs":    prefab_refs,
        "go_tags":        go_tags,
    }


# ── main ──────────────────────────────────────────────────────────────

def main():
    patterns = sys.argv[1:] if len(sys.argv) > 1 else ALL_PATTERNS

    print("Building full asset GUID index from all .meta files (lossless pass)...")
    asset_index = build_asset_guid_index(ASSETS_DIR)
    print(f"  {len(asset_index)} asset entries.\n")

    print("Building script GUID index from .cs.meta files...")
    script_index = build_script_guid_index(SCRIPTS_DIR)
    print(f"  {len(script_index)} script entries.\n")

    print("Building prefab GUID index from .prefab.meta files...")
    prefab_index = build_prefab_guid_index(PREFABS_DIR)
    print(f"  {len(prefab_index)} prefab entries.\n")

    # Write shared indexes
    asset_index_path = SCENE_ANALYSIS_DIR / "guid_to_asset.json"
    with open(asset_index_path, "w", encoding="utf-8") as f:
        json.dump(asset_index, f, indent=2, ensure_ascii=False)
    print(f"Wrote {asset_index_path.name}")

    script_index_path = SCENE_ANALYSIS_DIR / "guid_to_class.json"
    with open(script_index_path, "w", encoding="utf-8") as f:
        json.dump(script_index, f, indent=2, ensure_ascii=False)
    print(f"Wrote {script_index_path.name}")

    prefab_index_path = SCENE_ANALYSIS_DIR / "prefab_guid_index.json"
    with open(prefab_index_path, "w", encoding="utf-8") as f:
        json.dump(prefab_index, f, indent=2, ensure_ascii=False)
    print(f"Wrote {prefab_index_path.name}\n")

    ok = 0
    for pattern in patterns:
        result = annotate_pattern(pattern, script_index, prefab_index, asset_index)
        if result is None:
            print(f"  SKIP  {pattern} (no _parsed.json)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_scripts.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Summary
        total      = len(result["monobehaviours"])
        resolved   = sum(1 for v in result["monobehaviours"].values() if v["class_name"])
        unresolved = total - resolved
        n_prefabs  = len(result["prefab_refs"])

        flag = "  !" if unresolved else "   "
        line = f"{flag} {pattern}: {resolved}/{total} scene MBs resolved"
        if unresolved:
            line += f"  ({unresolved} built-in/unknown)"
        if n_prefabs:
            prefab_names = ", ".join(r["prefab_name"] for r in result["prefab_refs"])
            line += f"  | {n_prefabs} prefab ref(s): {prefab_names}"
        print(line)
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns annotated.")


if __name__ == "__main__":
    main()
