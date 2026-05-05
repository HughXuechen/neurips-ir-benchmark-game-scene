#!/usr/bin/env python3
"""
M4 Runtime Mechanism Adherence — static condition path comparison.

Compares the condition path (win/lose chain) extracted from LLM-generated
code against the ground truth condition path from the V2 pipeline.

This is a STATIC analysis — no Unity runtime needed. We run the same
condition path tracer (from trace_condition_path.py) on the LLM's
output_code and compare the resulting chain with the GT chain.

Dimensions:
  - path_present:   does the gen code have a win/lose path at all? (binary)
  - steps_f1:       F1 over the set of (actor_class, event) steps
  - effects_f1:     F1 over the set of effect strings
  - conditions_f1:  F1 over the set of condition expressions

Usage:
    uv run python src/evaluation/m4_mechanism_adherence.py \
        --jsonl results/v2_ir_*/evaluation/*.jsonl

    # Dry run (no JSONL update)
    uv run python src/evaluation/m4_mechanism_adherence.py \
        --jsonl results/v2_ir_*/evaluation/*.jsonl --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GT_DIR = ROOT / "data" / "processed" / "scene_analysis"

sys.path.insert(0, str(ROOT / "src"))
from scene_analysis.v2.trace_condition_path import (
    analyze_cs_file,
    trace_condition_paths,
)


def _f1_sets(gt: set, gen: set) -> float:
    if not gt and not gen:
        return 1.0
    if not gt or not gen:
        return 0.0
    intersection = len(gt & gen)
    precision = intersection / len(gen)
    recall = intersection / len(gt)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


# ── extract condition path from LLM code ──────────────────────────────

def extract_classes_from_code(code: str) -> dict[str, str]:
    """
    Extract (class_name, class_body) from LLM-generated code.
    Returns dict suitable for writing to temp files and analyzing.
    """
    classes: dict[str, str] = {}
    lines = code.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"^public\s+class\s+(\w+)", lines[i].strip())
        if not m:
            i += 1
            continue
        class_name = m.group(1)
        if class_name == "SceneBuilder":
            # Skip editor class — find its closing brace
            depth = 0
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if depth == 0 and lines[j].count("}") > 0:
                    i = j + 1
                    break
            else:
                i += 1
            continue

        # Extract full class text
        start = i
        depth = 0
        started = False
        for j in range(i, len(lines)):
            depth += lines[j].count("{") - lines[j].count("}")
            if depth > 0:
                started = True
            if started and depth == 0:
                class_text = "\n".join(lines[start:j + 1])
                # Wrap in using + namespace so it can be parsed
                full_text = "using UnityEngine;\n\n" + class_text
                classes[class_name] = full_text
                i = j + 1
                break
        else:
            i += 1

    return classes


def trace_gen_condition_path(output_code: str) -> dict:
    """
    Run condition path tracing on LLM-generated code.
    Returns { "win": [...], "lose": [...] } same format as GT.
    """
    import tempfile
    import os

    classes = extract_classes_from_code(output_code)
    if not classes:
        return {"win": [], "lose": []}

    # Write each class to a temp dir inside ROOT so relative_to works
    tmpdir = ROOT / ".tmp_m4"
    tmpdir.mkdir(exist_ok=True)
    all_scripts: dict[str, dict] = {}
    try:
        for class_name, class_text in classes.items():
            tmp_path = tmpdir / f"{class_name}.cs"
            tmp_path.write_text(class_text, encoding="utf-8")
            info = analyze_cs_file(tmp_path)
            info["class_name"] = class_name
            info["source_file"] = f"(generated)/{class_name}.cs"
            all_scripts[class_name] = info
    finally:
        for f in tmpdir.iterdir():
            f.unlink()
        tmpdir.rmdir()

    return trace_condition_paths(all_scripts)


# ── comparison ────────────────────────────────────────────────────────

def extract_step_signature(step: dict) -> str:
    """Canonical signature for a condition path step."""
    return f"{step['actor_class']}.{step['event']}"


def compare_paths(gt_path: list[dict], gen_path: list[dict]) -> dict:
    """Compare a single path (win or lose) between GT and gen."""
    gt_steps = {extract_step_signature(s) for s in gt_path}
    gen_steps = {extract_step_signature(s) for s in gen_path}

    gt_effects = {s["effect"] for s in gt_path}
    gen_effects = {s["effect"] for s in gen_path}

    gt_conditions: set[str] = set()
    for s in gt_path:
        gt_conditions.update(s.get("conditions", []))
    gen_conditions: set[str] = set()
    for s in gen_path:
        gen_conditions.update(s.get("conditions", []))

    return {
        "path_present": 1 if gen_path else 0,
        "gt_steps": len(gt_path),
        "gen_steps": len(gen_path),
        "steps_f1": round(_f1_sets(gt_steps, gen_steps), 4),
        "effects_f1": round(_f1_sets(gt_effects, gen_effects), 4),
        "conditions_f1": round(_f1_sets(gt_conditions, gen_conditions), 4),
        "gt_step_sigs": sorted(gt_steps),
        "gen_step_sigs": sorted(gen_steps),
        "steps_match": sorted(gt_steps & gen_steps),
        "steps_missing": sorted(gt_steps - gen_steps),
        "steps_extra": sorted(gen_steps - gt_steps),
    }


def compute_m4(gt_cpath: dict, gen_cpath: dict) -> dict:
    """Compute M4 scores per path. Lose fields are None if GT has no lose path."""
    win = compare_paths(gt_cpath.get("win", []), gen_cpath.get("win", []))

    gt_lose = gt_cpath.get("lose", [])
    lose = compare_paths(gt_lose, gen_cpath.get("lose", []))
    if not gt_lose:
        lose_steps_f1   = None
        lose_effects_f1 = None
        lose_conds_f1   = None
    else:
        lose_steps_f1   = lose["steps_f1"]
        lose_effects_f1 = lose["effects_f1"]
        lose_conds_f1   = lose["conditions_f1"]

    return {
        "win":  win,
        "lose": lose,
        "m4_win_steps_f1":    win["steps_f1"],
        "m4_win_effects_f1":  win["effects_f1"],
        "m4_win_conds_f1":    win["conditions_f1"],
        "m4_lose_steps_f1":   lose_steps_f1,
        "m4_lose_effects_f1": lose_effects_f1,
        "m4_lose_conds_f1":   lose_conds_f1,
    }


# ── main ──────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="M4 Mechanism Adherence")
    p.add_argument("--jsonl", nargs="+", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    results: list[dict] = []

    for jsonl_path in args.jsonl:
        jp = Path(jsonl_path)
        if not jp.exists():
            print(f"  [skip] {jsonl_path}")
            continue

        rows = []
        with open(jp, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))

        for row in rows:
            pattern_id = row.get("pattern_id", "")
            seed = row.get("seed", "?")
            model = row.get("model", "")
            output_code = row.get("output_code", "")
            run_id = row.get("run_id", "")

            # Load GT condition path
            gt_path = GT_DIR / f"{pattern_id}_condition_path.json"
            if not gt_path.exists():
                print(f"  [skip] {pattern_id} — no GT condition path")
                continue
            with open(gt_path, encoding="utf-8") as f:
                gt_cpath = json.load(f).get("condition_path", {})

            # Trace gen condition path
            gen_cpath = trace_gen_condition_path(output_code)

            # Compare
            m4 = compute_m4(gt_cpath, gen_cpath)

            result = {
                "pattern_id": pattern_id,
                "seed": seed,
                "model": model,
                "run_id": run_id,
                **m4,
            }
            results.append(result)

            w = m4["win"]
            l_sf = m4["m4_lose_steps_f1"]
            print(f"  {pattern_id:25s} seed={seed}  "
                  f"win(steps={w['steps_f1']:.2f} eff={w['effects_f1']:.2f} cond={w['conditions_f1']:.2f})  "
                  f"lose_steps={'null' if l_sf is None else f'{l_sf:.2f}'}")

        # Update JSONL
        if not args.dry_run and results:
            score_map = {r["run_id"]: r for r in results}
            updated = 0
            for row in rows:
                rid = row.get("run_id")
                if rid in score_map:
                    sr = score_map[rid]
                    row["m4_win_steps_f1"]    = sr["m4_win_steps_f1"]
                    row["m4_win_effects_f1"]  = sr["m4_win_effects_f1"]
                    row["m4_win_conds_f1"]    = sr["m4_win_conds_f1"]
                    row["m4_lose_steps_f1"]   = sr["m4_lose_steps_f1"]
                    row["m4_lose_effects_f1"] = sr["m4_lose_effects_f1"]
                    row["m4_lose_conds_f1"]   = sr["m4_lose_conds_f1"]
                    updated += 1
            with open(jp, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"  Updated {updated} rows in {jp.name}")

    # Summary + metrics output
    _M4_DIMS = [
        "m4_win_steps_f1", "m4_win_effects_f1", "m4_win_conds_f1",
        "m4_lose_steps_f1", "m4_lose_effects_f1", "m4_lose_conds_f1",
    ]
    if results:
        print(f"\n=== Summary ({len(results)} runs) ===")
        for dim in _M4_DIMS:
            vals = [r[dim] for r in results if r[dim] is not None]
            avg = sum(vals) / len(vals) if vals else float("nan")
            print(f"  Mean {dim}: {avg:.4f} (n={len(vals)})")

        # Write CSV
        metrics_dir = ROOT / "results" / "neurips" / "metrics" / "m4"
        metrics_dir.mkdir(parents=True, exist_ok=True)

        per_run_path = metrics_dir / "m4_per_run.csv"
        with open(per_run_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "pattern_id", "seed", "model",
                "m4_win_steps_f1", "m4_win_effects_f1", "m4_win_conds_f1",
                "m4_lose_steps_f1", "m4_lose_effects_f1", "m4_lose_conds_f1",
                "win_present", "win_steps_match", "win_steps_missing", "win_steps_extra",
                "lose_present", "n_gt_win_steps", "n_gen_win_steps",
            ])
            for r in sorted(results, key=lambda x: (x["pattern_id"], x["seed"])):
                wi = r["win"]
                lo = r["lose"]
                w.writerow([
                    r["pattern_id"], r["seed"], r["model"],
                    r["m4_win_steps_f1"], r["m4_win_effects_f1"], r["m4_win_conds_f1"],
                    r["m4_lose_steps_f1"], r["m4_lose_effects_f1"], r["m4_lose_conds_f1"],
                    wi["path_present"],
                    "|".join(wi["steps_match"]),
                    "|".join(wi["steps_missing"]),
                    "|".join(wi["steps_extra"]),
                    lo["path_present"],
                    wi["gt_steps"],
                    wi["gen_steps"],
                ])

        summary_path = metrics_dir / "m4_by_pattern.csv"
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["pattern_id", "n_runs",
                         "mean_win_steps_f1", "mean_win_effects_f1", "mean_win_conds_f1",
                         "mean_lose_steps_f1", "mean_lose_effects_f1", "mean_lose_conds_f1"])
            for pat in sorted(set(r["pattern_id"] for r in results)):
                pat_r = [r for r in results if r["pattern_id"] == pat]
                n = len(pat_r)
                def _m(dim: str) -> object:
                    v = [r[dim] for r in pat_r if r[dim] is not None]
                    return round(sum(v) / len(v), 4) if v else None
                w.writerow([pat, n,
                    _m("m4_win_steps_f1"), _m("m4_win_effects_f1"), _m("m4_win_conds_f1"),
                    _m("m4_lose_steps_f1"), _m("m4_lose_effects_f1"), _m("m4_lose_conds_f1")])

        detail_path = metrics_dir / "m4_detail.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\nMetrics written to:")
        print(f"  {per_run_path.relative_to(ROOT)}")
        print(f"  {summary_path.relative_to(ROOT)}")
        print(f"  {detail_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
