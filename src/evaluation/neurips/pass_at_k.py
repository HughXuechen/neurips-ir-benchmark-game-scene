#!/usr/bin/env python3
"""
pass@k evaluation using the unbiased estimator from Chen et al. (2021).

  pass@k = 1 - C(n-c, k) / C(n, k)

where n = total samples per problem, c = number passing, k = samples drawn.

Computes pass@1, pass@2, pass@3 per (condition, model, pattern), then
aggregates across patterns.

Reads M1-exec directly from replay logs (same logic as m1_funnel.py).

Usage:
    uv run python src/evaluation/pass_at_k.py \\
        --v4 results/replay/20260501-0655/logs \\
        --v2 results/replay/20260501-1353/logs \\
        --ns results/replay/20260502-0004/logs

Output:
    results/metrics/pass_at_k.csv
    results/metrics/pass_at_k.md
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_CSV = REPO_ROOT / "results" / "neurips" / "metrics" / "pass_at_k.csv"
OUT_MD  = REPO_ROOT / "results" / "neurips" / "metrics" / "pass_at_k.md"

_AWAKE_OK   = "GameBuilder.Awake(): OK"
_UNITY_EXIT = "MemoryLeaks"
_REAL_ERROR = re.compile(r"error CS(?!2001)\d+")

_MODEL_KEYS = {
    "Qwen3":   "Qwen3",
    "Qwen2.5": "Qwen2.5",
    "DeepSeek":"deepseek",
    "Gemma4":  "gemma",
}
_CONDITIONS = ["v4_ir", "v2_ir", "no_schema"]

def _read_eval_env() -> dict:
    p = REPO_ROOT / "local_doc/agent/eval_paths.env"
    out: dict = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


_EVAL_ENV = _read_eval_env()
_DEFAULT_V4 = REPO_ROOT / _EVAL_ENV.get("V4_LOGS", "results/replay/20260501-0655/logs")
_DEFAULT_V2 = REPO_ROOT / _EVAL_ENV.get("V2_LOGS", "results/replay/20260501-1353/logs")
_DEFAULT_NS = REPO_ROOT / _EVAL_ENV.get("NS_LOGS", "results/replay/20260502-0004/logs")


def _is_exec_pass(log: Path) -> bool:
    text = log.read_text(errors="ignore")
    return (not _REAL_ERROR.search(text)) and (_AWAKE_OK in text) and (_UNITY_EXIT in text)


def _pattern_from_log(log: Path) -> str:
    """Extract pattern_id from log filename stem."""
    # e.g. v4_ir_Qwen_Qwen3-..._seed0__20260430_192840_046
    # pattern is not in filename; read it from log content
    text = log.read_text(errors="ignore")
    m = re.search(r"pattern=(\S+)", text)
    return m.group(1) if m else "unknown"


def comb(n: int, k: int) -> float:
    if k > n:
        return 0.0
    return math.comb(n, k)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al. 2021)."""
    if n < k:
        return float("nan")
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def collect_per_pattern(logdir: Path, prefix: str) -> dict[tuple[str, str], tuple[int, int]]:
    """Return {(model, pattern): (n_pass, n_total)} across all seeds."""
    counts: dict[tuple[str, str], list[int]] = defaultdict(list)
    for mname, mkey in _MODEL_KEYS.items():
        for log in sorted(logdir.glob(f"{prefix}*{mkey}*.log")):
            pattern = _pattern_from_log(log)
            passed  = int(_is_exec_pass(log))
            counts[(mname, pattern)].append(passed)
    return {k: (sum(v), len(v)) for k, v in counts.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="pass@k evaluation.")
    parser.add_argument("--v4", type=Path, default=_DEFAULT_V4)
    parser.add_argument("--v2", type=Path, default=_DEFAULT_V2)
    parser.add_argument("--ns", type=Path, default=_DEFAULT_NS)
    args = parser.parse_args()

    log_dirs = {
        "v4_ir":    (args.v4, "v4_ir"),
        "v2_ir":    (args.v2, "v2_ir"),
        "no_schema":(args.ns, "no_schema"),
    }

    rows: list[dict] = []

    for cond, (logdir, prefix) in log_dirs.items():
        per_pattern = collect_per_pattern(logdir, prefix)

        # Aggregate pass@k per (cond, model)
        model_data: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for (mname, _pattern), (c, n) in per_pattern.items():
            model_data[mname].append((c, n))

        for mname, cn_list in sorted(model_data.items()):
            # Macro-average pass@k across patterns
            for k in (1, 2, 3):
                vals = [pass_at_k(n, c, k) for c, n in cn_list
                        if not math.isnan(pass_at_k(n, c, k))]
                macro = sum(vals) / len(vals) if vals else float("nan")
                rows.append(dict(condition=cond, model=mname, k=k,
                                 pass_at_k=round(macro, 4),
                                 n_patterns=len(vals)))

    # Write CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["condition","model","k","pass_at_k","n_patterns"])
        writer.writeheader()
        writer.writerows(rows)

    # Write markdown table (pivot: rows=cond×model, cols=pass@1/2/3)
    md_lines = ["| Condition | Model | pass@1 | pass@2 | pass@3 |",
                "|-----------|-------|--------|--------|--------|"]
    # Index rows by (cond, model)
    indexed: dict[tuple, dict] = {}
    for r in rows:
        indexed[(r["condition"], r["model"], r["k"])] = r["pass_at_k"]

    for cond in _CONDITIONS:
        for mname in _MODEL_KEYS:
            p1 = indexed.get((cond, mname, 1))
            p2 = indexed.get((cond, mname, 2))
            p3 = indexed.get((cond, mname, 3))
            if p1 is None:
                continue
            fmt = lambda v: f"{v:.3f}" if v is not None and not math.isnan(v) else "—"
            md_lines.append(f"| {cond} | {mname} | {fmt(p1)} | {fmt(p2)} | {fmt(p3)} |")

    md = "\n".join(md_lines)
    print(md)
    OUT_MD.write_text(md + "\n", encoding="utf-8")
    print(f"\nWritten: {OUT_CSV}")
    print(f"Written: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
