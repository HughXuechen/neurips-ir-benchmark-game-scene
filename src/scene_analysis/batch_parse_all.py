#!/usr/bin/env python3
"""Batch runner: parse + build_links for all scenes missing parsed/links files."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parse_unity_scene import parse_scene_file
from build_links import build_links

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent.parent
SCENE_DIR = ROOT / "data" / "raw" / "unity" / "PatternsUnityCode" / "Assets" / "Scenes" / "goal_flatten"
OUTPUT_DIR = ROOT / "data" / "processed" / "scene_analysis"

ALL_SCENES = [
    "1_Ownership", "2_Collection", "3_Eliminate", "4_Capture",
    "5_Overcome", "6_Evade", "7_Stealth", "8_Herd_Attract",
    "9_Conceal", "10_Rescue", "11_Delivery", "12_Guard",
    "13_Race", "14_Alignment_new", "15_Configuration", "16_Traverse",
    "17_Survive", "18_Connection_Line", "19_Exploration",
    "20_Reconnaissance", "21_Contact", "22_Enclosure",
    "23_GainCompetence", "24_GainInformation",
    "25_LastManStanding_Escaping", "26_KingoftheHill",
]

ALREADY_DONE = set()  # reprocess all scenes from goal_flatten


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    todo = [s for s in ALL_SCENES if s not in ALREADY_DONE]
    print(f"Batch processing {len(todo)} scenes (skipping {len(ALREADY_DONE)} already done)\n")
    ok, skip, fail = 0, 0, 0
    for name in todo:
        unity_path = SCENE_DIR / f"{name}.unity"
        if not unity_path.exists():
            print(f"  SKIP  {name} -- .unity file not found")
            skip += 1
            continue
        try:
            output_data, block_counts = parse_scene_file(unity_path)
            parsed_path = OUTPUT_DIR / f"{name}_parsed.json"
            with open(parsed_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            total_blocks = sum(block_counts.values())
            print(f"  PARSE {name} -- {total_blocks} blocks")
        except Exception as e:
            print(f"  FAIL  {name} parse -- {e}")
            fail += 1
            continue
        try:
            links_output, stats = build_links(parsed_path)
            links_path = OUTPUT_DIR / f"{name}_links.json"
            with open(links_path, "w", encoding="utf-8") as f:
                json.dump(links_output, f, indent=2, ensure_ascii=False)
            go = stats["total_gameobjects"]
            mb = stats["total_monobehaviours"]
            print(f"  LINKS {name} -- GOs={go}, MBs={mb}")
        except Exception as e:
            print(f"  FAIL  {name} links -- {e}")
            fail += 1
            continue
        ok += 1
    print(f"\nDone: {ok} succeeded, {skip} skipped, {fail} failed")


if __name__ == "__main__":
    main()
