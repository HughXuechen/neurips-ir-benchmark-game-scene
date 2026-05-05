#!/usr/bin/env python3
"""
Parse a generated Unity scene and produce gen_parsed.json / gen_links.json.

Reuses the existing parse_unity_scene.parse_scene_file() and
build_links.build_links() logic.

Usage:
    uv run python src/scene_analysis/parse_generated_scene.py \
        --scene results/unity_generated/<pattern_id>/<method>/<run_id>/scene.unity \
        --out-dir results/unity_generated/<pattern_id>/<method>/<run_id>/

    # Batch: parse all scene.unity files under results/unity_generated/
    uv run python src/scene_analysis/parse_generated_scene.py --batch
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path so sibling modules can be imported
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scene_analysis.parse_unity_scene import parse_scene_file
from scene_analysis.build_links import build_links


GEN_BASE = ROOT / "results" / "unity_generated"


def parse_and_export(scene_path: Path, out_dir: Path) -> bool:
    """Parse *scene_path*, write gen_parsed.json and gen_links.json to *out_dir*.

    Returns True on success.
    """
    if not scene_path.exists():
        print(f"  SKIP (not found): {scene_path}", file=sys.stderr)
        return False

    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: parse
    parsed_data, block_counts = parse_scene_file(str(scene_path))
    parsed_path = out_dir / "gen_parsed.json"
    with open(parsed_path, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)

    # Step 2: build links (build_links expects a file path)
    links_data, stats = build_links(str(parsed_path))
    links_path = out_dir / "gen_links.json"
    with open(links_path, "w", encoding="utf-8") as f:
        json.dump(links_data, f, indent=2, ensure_ascii=False)

    total = sum(block_counts.values())
    print(f"  OK  {scene_path.parent.name}: {total} blocks, "
          f"{stats['total_monobehaviours']} MonoBehaviours")
    return True


def batch_parse() -> int:
    """Find all scene.unity under results/unity_generated/ and parse them."""
    scenes = sorted(GEN_BASE.rglob("scene.unity"))
    if not scenes:
        print("No scene.unity files found under results/unity_generated/",
              file=sys.stderr)
        return 1

    ok = 0
    for sp in scenes:
        out_dir = sp.parent
        if parse_and_export(sp, out_dir):
            ok += 1

    print(f"\nParsed {ok}/{len(scenes)} scenes.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse generated Unity scene → gen_parsed.json + gen_links.json"
    )
    parser.add_argument("--scene", type=Path,
                        help="Path to a single scene.unity file")
    parser.add_argument("--out-dir", type=Path,
                        help="Output directory (defaults to scene's parent dir)")
    parser.add_argument("--batch", action="store_true",
                        help="Parse all scene.unity under results/unity_generated/")
    args = parser.parse_args()

    if args.batch:
        return batch_parse()

    if args.scene is None:
        parser.error("Provide --scene <path> or --batch")

    out_dir = args.out_dir or args.scene.parent
    ok = parse_and_export(args.scene, out_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
