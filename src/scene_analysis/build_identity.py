#!/usr/bin/env python3
"""
Stage 2: Homogeneous → Heterogeneous identity resolution.

Assigns every anonymous element in the scene a named identity:
  - scene MBs: resolved to C# class name via m_Script.guid
  - prefab asset refs: expanded into internal MB class names
  - all assets: indexed by GUID with type and path

Produces four shared index files and one per-pattern _identity.json.

Shared indexes (written once, used by all downstream stages):
  data/processed/scene_analysis/guid_to_asset.json
    { "<guid>": { "asset_type": "Texture2D", "asset_path": "Assets/..." } }
    Full index of all 360+ assets in the project. Built by scanning all
    .meta files. Provides type annotation for every GUID encountered
    in inspector fields, ensuring no reference is silently anonymous.

  data/processed/scene_analysis/guid_to_class.json
    { "<script_guid>": { "class_name": "SpawnManager", "source_file": "..." } }
    Index of custom C# scripts only (Assets/Scripts/**/*.cs).

  data/processed/scene_analysis/prefab_guid_index.json
    { "<prefab_guid>": { "prefab_name": "OwnershipObject", "prefab_path": "..." } }

Per-pattern output:
  data/processed/scene_analysis/<N>_<PatternName>_identity.json
    {
      "scene": "1_Ownership",
      "monobehaviours": {
        "<mb_fileID>": {
          "go_id":       "<parent GO fileID>",
          "go_name":     "Spawn Manager",
          "guid":        "<m_Script.guid>",
          "class_name":  "SpawnManager",        # null if Unity built-in
          "source_file": "Assets/Scripts/..."   # null if Unity built-in
        }
      },
      "prefab_refs": [
        {
          "from_mb":    "<scene MB fileID>",
          "from_class": "SpawnManager",
          "field":      "spawnPrefab",
          "prefab_guid":  "<asset guid>",
          "prefab_name":  "OwnershipObject",
          "prefab_path":  "data/raw/.../OwnershipObject.prefab",
          "prefab_monobehaviours": {
            "<prefab MB fileID>": {
              "guid":        "<script guid>",
              "class_name":  "ChangeColor",
              "source_file": "Assets/Scripts/ChangeColor.cs"
            }
          }
        }
      ]
    }

Usage:
    uv run python src/scene_analysis/build_identity.py            # all patterns
    uv run python src/scene_analysis/build_identity.py 1_Ownership
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

# File extension → Unity asset type label (for guid_to_asset.json)
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


# ── GUID indexes ──────────────────────────────────────────────────────

def build_asset_guid_index(assets_dir: Path) -> dict[str, dict]:
    """
    Walk ALL .meta files under assets_dir.
    Return { guid: { "asset_type": str, "asset_path": str } } for every
    non-folder asset. asset_type derived from file extension.
    This is the lossless full-project asset index.
    """
    index: dict[str, dict] = {}
    for meta_path in assets_dir.rglob("*.meta"):
        text = meta_path.read_text(encoding="utf-8", errors="replace")
        if "folderAsset: yes" in text:
            continue
        m = _GUID_RE.search(text)
        if not m:
            continue
        guid = m.group(1)
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
    """
    index: dict[str, dict] = {}
    for meta_path in scripts_dir.rglob("*.cs.meta"):
        text = meta_path.read_text(encoding="utf-8")
        m = _GUID_RE.search(text)
        if not m:
            continue
        guid = m.group(1)
        cs_path = meta_path.with_suffix("")
        index[guid] = {
            "class_name":  cs_path.stem,
            "source_file": str(cs_path.relative_to(ROOT)),
        }
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
        prefab_path = meta_path.with_suffix("")
        index[guid] = {
            "prefab_name": prefab_path.stem,
            "prefab_path": str(prefab_path.relative_to(ROOT)),
        }
    return index


# ── prefab content parser ─────────────────────────────────────────────

def parse_prefab_monobehaviours(prefab_path: Path,
                                script_index: dict[str, dict]) -> dict[str, dict]:
    """
    Parse a .prefab file and return all MonoBehaviour blocks with resolved
    class names.
    Return { mb_fileID: { "guid", "class_name", "source_file" } }.
    """
    text = prefab_path.read_text(encoding="utf-8")
    result: dict[str, dict] = {}
    headers = list(_BLOCK_HEADER_RE.finditer(text))
    for i, header in enumerate(headers):
        if int(header.group(1)) != 114:   # 114 = MonoBehaviour
            continue
        file_id   = header.group(2)
        body_start = header.end()
        body_end   = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body       = text[body_start:body_end]
        script_m   = re.search(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-f]{32})", body)
        if not script_m:
            continue
        guid     = script_m.group(1)
        resolved = script_index.get(guid, {})
        result[file_id] = {
            "guid":        guid,
            "class_name":  resolved.get("class_name"),
            "source_file": resolved.get("source_file"),
        }
    return result


# ── scene annotation ──────────────────────────────────────────────────

def _asset_guid_fields(mb_data: dict) -> list[tuple[str, str]]:
    """Return (field_name, guid) for all non-m_ fields holding an asset GUID."""
    hits = []
    for field, value in mb_data.items():
        if field.startswith("m_"):
            continue
        if isinstance(value, dict):
            guid = value.get("guid")
            if guid and isinstance(guid, str) and len(guid) == 32:
                hits.append((field, guid))
    return hits


def build_identity(
    pattern: str,
    script_index: dict[str, dict],
    prefab_index: dict[str, dict],
) -> dict | None:
    """
    Resolve identity for all scene MBs and prefab refs in one pattern.
    Returns the _identity.json payload, or None if _parsed.json is missing.
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

    # Scene MBs
    monobehaviours: dict[str, dict] = {}
    for block in parsed.get("blocksByType", {}).get("MonoBehaviour", []):
        mb_fid  = str(block["fileID"])
        mb_data = block["data"].get("MonoBehaviour", {})
        guid    = mb_data.get("m_Script", {}).get("guid")
        go_id   = comp_to_go.get(mb_fid)
        go_name = go_names.get(go_id, "") if go_id else ""
        resolved = script_index.get(guid, {}) if guid else {}
        monobehaviours[mb_fid] = {
            "go_id":       go_id,
            "go_name":     go_name,
            "guid":        guid,
            "class_name":  resolved.get("class_name"),
            "source_file": resolved.get("source_file"),
        }

    # Prefab refs — expand internal MB structure
    prefab_refs: list[dict] = []
    for block in parsed.get("blocksByType", {}).get("MonoBehaviour", []):
        mb_fid     = str(block["fileID"])
        mb_data    = block["data"].get("MonoBehaviour", {})
        from_class = monobehaviours.get(mb_fid, {}).get("class_name")
        for field, asset_guid in _asset_guid_fields(mb_data):
            if asset_guid not in prefab_index:
                # Not a prefab — cannot expand (no internal MB structure).
                # Identity recorded in _inspector.json via asset_type/asset_path.
                continue
            prefab_info = prefab_index[asset_guid]
            prefab_path = ROOT / prefab_info["prefab_path"]
            prefab_mbs: dict[str, dict] = {}
            if prefab_path.exists():
                prefab_mbs = parse_prefab_monobehaviours(prefab_path, script_index)
            prefab_refs.append({
                "from_mb":               mb_fid,
                "from_class":            from_class,
                "field":                 field,
                "prefab_guid":           asset_guid,
                "prefab_name":           prefab_info["prefab_name"],
                "prefab_path":           prefab_info["prefab_path"],
                "prefab_monobehaviours": prefab_mbs,
            })

    return {
        "scene":          pattern,
        "monobehaviours": monobehaviours,
        "prefab_refs":    prefab_refs,
    }


# ── main ──────────────────────────────────────────────────────────────

def main():
    patterns = sys.argv[1:] if len(sys.argv) > 1 else ALL_PATTERNS

    print("Building full asset GUID index from all .meta files...")
    asset_index = build_asset_guid_index(ASSETS_DIR)
    print(f"  {len(asset_index)} asset entries.")

    print("Building script GUID index from .cs.meta files...")
    script_index = build_script_guid_index(SCRIPTS_DIR)
    print(f"  {len(script_index)} script entries.")

    print("Building prefab GUID index from .prefab.meta files...")
    prefab_index = build_prefab_guid_index(PREFABS_DIR)
    print(f"  {len(prefab_index)} prefab entries.\n")

    # Write shared indexes
    for path, data in [
        (SCENE_ANALYSIS_DIR / "guid_to_asset.json",    asset_index),
        (SCENE_ANALYSIS_DIR / "guid_to_class.json",    script_index),
        (SCENE_ANALYSIS_DIR / "prefab_guid_index.json", prefab_index),
    ]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Wrote {path.name}")
    print()

    ok = 0
    for pattern in patterns:
        result = build_identity(pattern, script_index, prefab_index)
        if result is None:
            print(f"  SKIP  {pattern} (no _parsed.json)")
            continue

        out_path = SCENE_ANALYSIS_DIR / f"{pattern}_identity.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        total      = len(result["monobehaviours"])
        resolved   = sum(1 for v in result["monobehaviours"].values() if v["class_name"])
        unresolved = total - resolved
        n_prefabs  = len(result["prefab_refs"])
        flag = "  !" if unresolved else "   "
        line = f"{flag} {pattern}: {resolved}/{total} MBs resolved"
        if unresolved:
            line += f"  ({unresolved} built-in)"
        if n_prefabs:
            line += f"  | prefabs: {', '.join(r['prefab_name'] for r in result['prefab_refs'])}"
        print(line)
        ok += 1

    print(f"\nDone: {ok}/{len(patterns)} patterns.")


if __name__ == "__main__":
    main()
