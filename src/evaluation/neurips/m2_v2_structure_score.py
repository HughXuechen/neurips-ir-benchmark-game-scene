#!/usr/bin/env python3
"""
M2 Structure Score (V2 IR edition)

Compares generated scenes against ground truth using the same analysis
dimensions as V2 IR: scripts, inspector fields, components, tags.

For each generated scene:
  1. Parse gen scene → gen_parsed.json (must exist, run parse_generated_scenes.py first)
  2. Extract script classes from both GT and gen parsed JSONs
  3. Compare: script class overlap, GO count ratio, component type overlap

Scoring:
    Dimensions reported separately (no weighted aggregation):
    scripts_f1 | go_names_f1 | component_f1 | tags_f1 | inspector_match

Usage:
    uv run python src/evaluation/m2_v2_structure_score.py \
        --jsonl results/v2_ir_*/evaluation/*.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GT_DIR = ROOT / "data" / "processed" / "scene_analysis"
GEN_BASE = ROOT / "results" / "unity_generated"


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _f1(gt: Counter, gen: Counter) -> float:
    if not gt and not gen:
        return 1.0
    if not gt or not gen:
        return 0.0
    intersection = sum((gt & gen).values())
    precision = intersection / sum(gen.values())
    recall = intersection / sum(gt.values())
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _ratio(a: int, b: int) -> float:
    if a == 0 and b == 0:
        return 1.0
    if a == 0 or b == 0:
        return 0.0
    return min(a, b) / max(a, b)


# ── extraction helpers ────────────────────────────────────────────────

def extract_gt_class_names(pattern_id: str) -> Counter:
    """Extract class names from GT manifest (V2 pipeline output)."""
    manifest_path = GT_DIR / f"{pattern_id}_manifest.json"
    if not manifest_path.exists():
        return Counter()
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    return Counter(manifest.get("scripts", {}).keys())


def extract_gen_class_names(output_code: str) -> Counter:
    """Extract class names defined in LLM-generated code."""
    # Match 'public class ClassName' but skip SceneBuilder (Editor-only)
    classes = re.findall(r"public\s+class\s+(\w+)", output_code)
    return Counter(c for c in classes if c != "SceneBuilder")


def extract_go_count(parsed: dict) -> int:
    return len(parsed.get("blocksByType", {}).get("GameObject", []))


def extract_component_types(parsed: dict) -> Counter:
    """Count of each component block type (excluding settings blocks)."""
    skip = {"OcclusionCullingSettings", "RenderSettings", "LightmapSettings", "NavMeshSettings"}
    types: Counter = Counter()
    for btype, blocks in parsed.get("blocksByType", {}).items():
        if btype not in skip:
            types[btype] += len(blocks)
    return types


def extract_tags(parsed: dict) -> Counter:
    tags: Counter = Counter()
    for blk in parsed.get("blocksByType", {}).get("GameObject", []):
        tag = blk.get("data", {}).get("GameObject", {}).get("m_TagString", "")
        if tag and tag != "Untagged":
            tags[tag] += 1
    return tags


def extract_go_names(parsed: dict) -> Counter:
    """Extract GO name multiset from GameObject blocks."""
    names: list[str] = []
    for blk in parsed.get("blocksByType", {}).get("GameObject", []):
        name = blk.get("data", {}).get("GameObject", {}).get("m_Name", "")
        if name:
            names.append(name)
    return Counter(names)


def extract_gt_inspector_values(pattern_id: str) -> dict[str, dict]:
    """Extract inspector field values from GT extraction (V2 pipeline output)."""
    ext_path = GT_DIR / f"{pattern_id}_extraction.json"
    if not ext_path.exists():
        return {}
    with open(ext_path, encoding="utf-8") as f:
        ext = json.load(f)
    result: dict[str, dict] = {}
    for cls, info in ext.get("inspector_values", {}).items():
        fields = info.get("fields", {})
        # Only keep scalar values (not fileID refs)
        scalars = {}
        for k, v in fields.items():
            if isinstance(v, (int, float, bool, str)):
                scalars[k] = v
        if scalars:
            result[cls] = scalars
    return result


def extract_gen_inspector_values(output_code: str) -> dict[str, dict]:
    """
    Extract inspector field assignments from LLM-generated code.
    Looks for patterns like: variableName.fieldName = value;
    """
    result: dict[str, dict] = {}
    # Match: someVar.fieldName = value;
    # We need to figure out which class the variable belongs to.
    # Strategy: find AddComponent<ClassName>() → variable name mapping,
    # then find variable.field = value assignments.
    var_to_class: dict[str, str] = {}
    for m in re.finditer(r'var\s+(\w+)\s*=\s*\w+\.AddComponent<(\w+)>\(\)', output_code):
        var_to_class[m.group(1)] = m.group(2)

    for var, cls in var_to_class.items():
        fields: dict[str, object] = {}
        # Match: var.field = value;
        for m in re.finditer(rf'{var}\.(\w+)\s*=\s*(.+?);', output_code):
            field_name = m.group(1)
            value_str = m.group(2).strip()
            # Parse value
            if value_str in ("true", "True"):
                fields[field_name] = True
            elif value_str in ("false", "False"):
                fields[field_name] = False
            elif value_str == "null":
                continue
            else:
                try:
                    fields[field_name] = int(value_str)
                except ValueError:
                    try:
                        fields[field_name] = float(value_str.rstrip("f"))
                    except ValueError:
                        continue
        if fields:
            result[cls] = fields
    return result


def compute_inspector_match(gt_vals: dict[str, dict], gen_vals: dict[str, dict]) -> tuple[float, dict]:
    """
    Compare inspector field values between GT and gen.
    Returns (match_ratio, detail_dict).
    match_ratio = number of matching field values / total GT field values.
    """
    total = 0
    matched = 0
    mismatched: list[dict] = []

    for cls, gt_fields in gt_vals.items():
        gen_fields = gen_vals.get(cls, {})
        for field, gt_val in gt_fields.items():
            total += 1
            gen_val = gen_fields.get(field)
            if gen_val is not None and _values_match(gt_val, gen_val):
                matched += 1
            else:
                mismatched.append({
                    "class": cls, "field": field,
                    "gt": gt_val, "gen": gen_val,
                })

    ratio = matched / total if total > 0 else 1.0
    return ratio, {
        "total_fields": total,
        "matched": matched,
        "mismatched": mismatched,
    }


def _values_match(a: object, b: object) -> bool:
    """Compare two values with tolerance for floats."""
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 0.01
        except (TypeError, ValueError):
            return False
    return a == b


# ── scoring ───────────────────────────────────────────────────────────

def compute_score(
    gt_parsed: dict,
    gen_parsed: dict,
    pattern_id: str,
    output_code: str,
) -> dict:
    # 1. Scripts: compare by class name
    gt_scripts = extract_gt_class_names(pattern_id)
    gen_scripts = extract_gen_class_names(output_code)
    scripts_f1 = _f1(gt_scripts, gen_scripts)

    # 2. GO names: compare by name (not just count)
    gt_go_names = extract_go_names(gt_parsed)
    gen_go_names = extract_go_names(gen_parsed)
    go_names_f1 = _f1(gt_go_names, gen_go_names)

    # 3. Component types
    gt_comp = extract_component_types(gt_parsed)
    gen_comp = extract_component_types(gen_parsed)
    comp_f1 = _f1(gt_comp, gen_comp)

    # 4. Tags
    gt_tags = extract_tags(gt_parsed)
    gen_tags = extract_tags(gen_parsed)
    tags_f1 = _f1(gt_tags, gen_tags)

    # 5. Inspector values: did LLM use the right numbers?
    gt_insp = extract_gt_inspector_values(pattern_id)
    gen_insp = extract_gen_inspector_values(output_code)
    inspector_match, inspector_detail = compute_inspector_match(gt_insp, gen_insp)

    # Report all sub-scores individually — no weighted aggregate.
    # Consumers can weight as they see fit.
    return {
        "scripts_f1":       round(scripts_f1, 4),
        "go_names_f1":      round(go_names_f1, 4),
        "component_f1":     round(comp_f1, 4),
        "tags_f1":          round(tags_f1, 4),
        "inspector_match":  round(inspector_match, 4),
        "detail": {
            "gt_scripts": sorted(gt_scripts.keys()),
            "gen_scripts": sorted(gen_scripts.keys()),
            "scripts_match": sorted(set(gt_scripts) & set(gen_scripts)),
            "scripts_missing": sorted(set(gt_scripts) - set(gen_scripts)),
            "scripts_extra": sorted(set(gen_scripts) - set(gt_scripts)),
            "gt_go_names": sorted(gt_go_names.keys()),
            "gen_go_names": sorted(gen_go_names.keys()),
            "go_names_match": sorted(set(gt_go_names) & set(gen_go_names)),
            "go_names_missing": sorted(set(gt_go_names) - set(gen_go_names)),
            "gt_tags": dict(gt_tags),
            "gen_tags": dict(gen_tags),
            "inspector": inspector_detail,
        },
    }


# ── main ──────────────────────────────────────────────────────────────

def find_gen_parsed(pattern_id: str, method: str, run_id: str, model: str) -> Path | None:
    """Find gen_parsed.json for a specific run."""
    # Try model-slug path structure
    model_slug = model.replace("/", "_")
    candidates = [
        GEN_BASE / model_slug / pattern_id / method / run_id / "gen_parsed.json",
        GEN_BASE / pattern_id / method / run_id / "gen_parsed.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fallback: search
    for p in GEN_BASE.rglob(f"{run_id}/gen_parsed.json"):
        return p
    return None


def main():
    p = argparse.ArgumentParser(description="M2 Structure Score (V2 edition)")
    p.add_argument("--jsonl", nargs="+", required=True, help="Evaluation JSONL file(s)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    results: list[dict] = []

    for jsonl_path in args.jsonl:
        jp = Path(jsonl_path)
        if not jp.exists():
            print(f"  [skip] {jsonl_path} not found")
            continue

        rows = []
        with open(jp, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))

        for row in rows:
            pattern_id = row.get("pattern_id", "")
            run_id = row.get("run_id", "")
            method = row.get("method", "")
            model = row.get("model", "")
            seed = row.get("seed", "?")

            # Load ground truth
            gt_path = GT_DIR / f"{pattern_id}_parsed.json"
            gt_parsed = _load(gt_path)
            if gt_parsed is None:
                continue

            # Load generated
            gen_path = find_gen_parsed(pattern_id, method, run_id, model)
            if gen_path is None:
                print(f"  [skip] {pattern_id} seed={seed} — no gen_parsed.json")
                continue
            gen_parsed = _load(gen_path)
            if gen_parsed is None:
                continue

            output_code = row.get("output_code", "")
            score = compute_score(gt_parsed, gen_parsed, pattern_id, output_code)
            score["pattern_id"] = pattern_id
            score["seed"] = seed
            score["model"] = model
            score["run_id"] = run_id
            results.append(score)

            print(f"  {pattern_id:25s} seed={seed}  "
                  f"scripts={score['scripts_f1']:.2f}  "
                  f"go_names={score['go_names_f1']:.2f}  "
                  f"comp={score['component_f1']:.2f}  "
                  f"tags={score['tags_f1']:.2f}  "
                  f"inspector={score['inspector_match']:.2f}")

        # Update JSONL with scores
        if not args.dry_run and results:
            score_map = {r["run_id"]: r for r in results}
            updated = 0
            for row in rows:
                rid = row.get("run_id")
                if rid in score_map:
                    s = score_map[rid]
                    row["m2_scripts_f1"] = s["scripts_f1"]
                    row["m2_go_names_f1"] = s["go_names_f1"]
                    row["m2_component_f1"] = s["component_f1"]
                    row["m2_tags_f1"] = s["tags_f1"]
                    row["m2_inspector_match"] = s["inspector_match"]
                    updated += 1
            with open(jp, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"  Updated {updated} rows in {jp.name}")

    DIMS = ["scripts_f1", "go_names_f1", "component_f1", "tags_f1", "inspector_match"]

    # Summary + metrics output
    if results:
        print(f"\n=== Summary ({len(results)} runs) ===")
        for dim in DIMS:
            avg = sum(r[dim] for r in results) / len(results)
            print(f"  {dim:20s} mean={avg:.4f}")
        print()
        for pat in sorted(set(r["pattern_id"] for r in results)):
            pat_r = [r for r in results if r["pattern_id"] == pat]
            vals = "  ".join(f"{d}={sum(r[d] for r in pat_r)/len(pat_r):.2f}" for d in DIMS)
            print(f"  {pat:25s} ({len(pat_r)} runs)  {vals}")

        # Write CSV tables
        metrics_dir = ROOT / "results" / "neurips" / "metrics" / "m2"
        metrics_dir.mkdir(parents=True, exist_ok=True)

        import csv
        # Per-run CSV
        per_run_path = metrics_dir / "m2_v2_per_run.csv"
        with open(per_run_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["pattern_id", "seed", "model"] + DIMS + [
                "scripts_match", "scripts_missing", "scripts_extra",
                "go_names_match", "go_names_missing",
                "inspector_matched", "inspector_total", "inspector_mismatched",
            ])
            for r in sorted(results, key=lambda x: (x["pattern_id"], x["seed"])):
                d = r.get("detail", {})
                insp = d.get("inspector", {})
                w.writerow([
                    r["pattern_id"], r["seed"], r["model"],
                    *[r[dim] for dim in DIMS],
                    "|".join(d.get("scripts_match", [])),
                    "|".join(d.get("scripts_missing", [])),
                    "|".join(d.get("scripts_extra", [])),
                    "|".join(d.get("go_names_match", [])),
                    "|".join(d.get("go_names_missing", [])),
                    insp.get("matched", ""),
                    insp.get("total_fields", ""),
                    "|".join(
                        f"{m['class']}.{m['field']}({m['gt']}→{m['gen']})"
                        for m in insp.get("mismatched", [])
                    ),
                ])

        # Per-pattern summary CSV
        summary_path = metrics_dir / "m2_v2_by_pattern.csv"
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["pattern_id", "n_runs"] + [f"mean_{d}" for d in DIMS])
            for pat in sorted(set(r["pattern_id"] for r in results)):
                pat_r = [r for r in results if r["pattern_id"] == pat]
                n = len(pat_r)
                w.writerow([
                    pat, n,
                    *[round(sum(r[d] for r in pat_r) / n, 4) for d in DIMS],
                ])

        # Full detail JSON
        detail_path = metrics_dir / "m2_v2_detail.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\nMetrics written to:")
        print(f"  {per_run_path.relative_to(ROOT)}")
        print(f"  {summary_path.relative_to(ROOT)}")
        print(f"  {detail_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
