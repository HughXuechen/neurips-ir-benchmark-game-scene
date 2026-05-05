#!/usr/bin/env python3
"""
Statistical significance tests for M1-exec pairwise condition comparisons.

For each (model, pattern), compares whether pass rates differ between conditions
using McNemar's test (paired, since same patterns appear across conditions).

Reports:
  - p-value (McNemar's test, exact)
  - Odds ratio + 95% CI
  - Cohen's h (effect size for proportions)

Pairwise comparisons: v4_ir vs v2_ir, v4_ir vs no_schema, v2_ir vs no_schema

Usage:
    uv run python src/evaluation/statistical_tests.py \\
        --v4 results/replay/20260501-0655/logs \\
        --v2 results/replay/20260501-1353/logs \\
        --ns results/replay/20260502-0004/logs

Output:
    results/metrics/statistical_tests.csv
    results/metrics/statistical_tests.md
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from scipy.stats import chi2

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_CSV = REPO_ROOT / "results" / "neurips" / "metrics" / "statistical_tests.csv"
OUT_MD  = REPO_ROOT / "results" / "neurips" / "metrics" / "statistical_tests.md"

_AWAKE_OK   = "GameBuilder.Awake(): OK"
_UNITY_EXIT = "MemoryLeaks"
_REAL_ERROR = re.compile(r"error CS(?!2001)\d+")

_MODEL_KEYS = {
    "Qwen3":   "Qwen3",
    "Qwen2.5": "Qwen2.5",
    "DeepSeek":"deepseek",
    "Gemma4":  "gemma",
}

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
    text = log.read_text(errors="ignore")
    m = re.search(r"pattern=(\S+)", text)
    return m.group(1) if m else "unknown"


def collect(logdir: Path, prefix: str) -> dict[tuple[str, str], list[int]]:
    """Return {(model, pattern): [0/1 per seed]}."""
    data: dict[tuple[str, str], list[int]] = defaultdict(list)
    for mname, mkey in _MODEL_KEYS.items():
        for log in sorted(logdir.glob(f"{prefix}*{mkey}*.log")):
            pat = _pattern_from_log(log)
            data[(mname, pat)].append(int(_is_exec_pass(log)))
    return data


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value (binomial sign test)."""
    n = b + c
    if n == 0:
        return 1.0
    # P(X >= max(b,c)) * 2 under H0: X ~ Binomial(n, 0.5)
    k = max(b, c)
    p = 0.0
    for i in range(k, n + 1):
        p += math.comb(n, i) * (0.5 ** n)
    return min(2 * p, 1.0)


def odds_ratio_ci(b: int, c: int, alpha: float = 0.05) -> tuple[float, float, float]:
    """OR = b/c with Woolf logit CI. Returns (OR, lower, upper)."""
    if c == 0 or b == 0:
        return (float("nan"), float("nan"), float("nan"))
    or_val = b / c
    z = 1.96  # approx for 95% CI
    se = math.sqrt(1/b + 1/c)
    lo = math.exp(math.log(or_val) - z * se)
    hi = math.exp(math.log(or_val) + z * se)
    return (or_val, lo, hi)


def cohen_h(p1: float, p2: float) -> float:
    """Cohen's h effect size for two proportions."""
    return 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))


def compare(data_a: dict, data_b: dict, label_a: str, label_b: str) -> list[dict]:
    """Pairwise McNemar per model across all patterns."""
    rows = []
    # Group by model
    models = sorted({m for m, _ in data_a} | {m for m, _ in data_b})
    for model in models:
        # Collect paired outcomes across patterns
        # a_pass but not b: discord b
        # b_pass but not a: discord c
        b_count = c_count = n_agree = 0
        n_a = n_b = 0
        pass_a = pass_b = 0

        pats_a = {pat: sum(v)/len(v) for (m, pat), v in data_a.items() if m == model}
        pats_b = {pat: sum(v)/len(v) for (m, pat), v in data_b.items() if m == model}
        shared = sorted(set(pats_a) & set(pats_b))

        if not shared:
            continue

        for pat in shared:
            # any-pass: >=1 seed pass counts as pass for this pattern
            va = int(sum(data_a[(model, pat)]) > 0)
            vb = int(sum(data_b[(model, pat)]) > 0)
            if va == 1 and vb == 0:
                b_count += 1
            elif va == 0 and vb == 1:
                c_count += 1
            else:
                n_agree += 1
            n_a += va; n_b += vb

        n = len(shared)
        p_val = mcnemar_exact(b_count, c_count)
        or_val, or_lo, or_hi = odds_ratio_ci(b_count, c_count)
        prop_a = n_a / n if n else 0
        prop_b = n_b / n if n else 0
        h = cohen_h(prop_a, prop_b) if prop_a > 0 and prop_b > 0 else float("nan")

        rows.append(dict(
            comparison=f"{label_a} vs {label_b}",
            model=model,
            n_patterns=n,
            n_pass_a=n_a, n_pass_b=n_b,
            prop_a=round(prop_a, 3), prop_b=round(prop_b, 3),
            b=b_count, c=c_count,
            p_value=round(p_val, 4),
            odds_ratio=round(or_val, 3) if not math.isnan(or_val) else "—",
            or_lo=round(or_lo, 3) if not math.isnan(or_lo) else "—",
            or_hi=round(or_hi, 3) if not math.isnan(or_hi) else "—",
            cohen_h=round(abs(h), 3) if not math.isnan(h) else "—",
            significant="*" if p_val < 0.05 else "",
        ))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Statistical tests for M1-exec.")
    parser.add_argument("--v4", type=Path, default=_DEFAULT_V4)
    parser.add_argument("--v2", type=Path, default=_DEFAULT_V2)
    parser.add_argument("--ns", type=Path, default=_DEFAULT_NS)
    args = parser.parse_args()

    data_v4 = collect(args.v4, "v4_ir")
    data_v2 = collect(args.v2, "v2_ir")
    data_ns = collect(args.ns, "no_schema")

    all_rows = []
    all_rows += compare(data_v4, data_v2, "v4_ir", "v2_ir")
    all_rows += compare(data_v4, data_ns, "v4_ir", "no_schema")
    all_rows += compare(data_v2, data_ns, "v2_ir", "no_schema")

    # Write CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = ["comparison","model","n_patterns","n_pass_a","n_pass_b",
              "prop_a","prop_b","b","c","p_value","odds_ratio",
              "or_lo","or_hi","cohen_h","significant"]
    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    # Markdown
    md_lines = [
        "| Comparison | Model | prop_A | prop_B | p-value | OR [95% CI] | Cohen h | sig |",
        "|------------|-------|--------|--------|---------|-------------|---------|-----|",
    ]
    for r in all_rows:
        ci = f"{r['odds_ratio']} [{r['or_lo']}–{r['or_hi']}]"
        md_lines.append(
            f"| {r['comparison']} | {r['model']} | {r['prop_a']} | {r['prop_b']} "
            f"| {r['p_value']} | {ci} | {r['cohen_h']} | {r['significant']} |"
        )

    md = "\n".join(md_lines)
    print(md)
    OUT_MD.write_text(md + "\n", encoding="utf-8")
    print(f"\nWritten: {OUT_CSV}")
    print(f"Written: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
