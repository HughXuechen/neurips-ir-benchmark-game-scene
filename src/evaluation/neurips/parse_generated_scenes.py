#!/usr/bin/env python3
"""
Parse generated scene.unity files for M2 evaluation.

Finds all scene.unity files under results/unity_generated/, runs them
through the same parser used for ground truth scenes (parse_unity_scene.py
+ build_links.py), and outputs gen_parsed.json + gen_links.json alongside
each scene.unity.

These files are required by m2_structure_score.py.

Usage:
    uv run python src/evaluation/parse_generated_scenes.py

    # Only parse scenes from a specific experiment
    uv run python src/evaluation/parse_generated_scenes.py \
        --dir results/unity_generated/Qwen/Qwen3-Coder-30B-A3B-Instruct
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from scene_analysis.parse_unity_scene import parse_scene_file
from scene_analysis.build_links import build_links


def parse_scene_dir(scene_dir: Path) -> bool:
    """Parse a single scene.unity and write gen_parsed.json + gen_links.json."""
    scene_path = scene_dir / "scene.unity"
    if not scene_path.exists():
        return False

    parsed_path = scene_dir / "gen_parsed.json"
    links_path = scene_dir / "gen_links.json"

    # Skip if already parsed
    if parsed_path.exists() and links_path.exists():
        return True

    try:
        import json
        parsed, _ = parse_scene_file(str(scene_path))
        with open(parsed_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)

        links_output, _ = build_links(str(parsed_path))
        with open(links_path, "w", encoding="utf-8") as f:
            json.dump(links_output, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        print(f"  ERROR: {scene_dir.name}: {e}")
        return False


def main():
    p = argparse.ArgumentParser(description="Parse generated scenes for M2 evaluation.")
    p.add_argument("--dir", type=Path, default=ROOT / "results" / "unity_generated",
                   help="Root directory to search for scene.unity files")
    p.add_argument("--force", action="store_true",
                   help="Re-parse even if gen_parsed.json already exists")
    args = p.parse_args()

    scene_dirs = []
    for scene_file in sorted(args.dir.rglob("scene.unity")):
        scene_dirs.append(scene_file.parent)

    if not scene_dirs:
        print(f"No scene.unity files found under {args.dir}")
        sys.exit(1)

    print(f"Found {len(scene_dirs)} generated scenes.\n")

    ok = 0
    skip = 0
    fail = 0
    for sd in scene_dirs:
        parsed_exists = (sd / "gen_parsed.json").exists()
        if parsed_exists and not args.force:
            skip += 1
            continue
        if parsed_exists and args.force:
            (sd / "gen_parsed.json").unlink()
            (sd / "gen_links.json").unlink(missing_ok=True)

        rel = sd.relative_to(args.dir)
        if parse_scene_dir(sd):
            print(f"  OK  {rel}")
            ok += 1
        else:
            print(f"  FAIL {rel}")
            fail += 1

    print(f"\nDone: {ok} parsed, {skip} skipped (already done), {fail} failed.")


if __name__ == "__main__":
    main()
