#!/usr/bin/env python3
"""
Generate M1/M2/M4 summary table for paper.

Reads:
  - M1-exec from replay log dirs (via m1_funnel logic)
  - M2 / M4 from patched JSONL files (m2_*/m4_* fields injected by eval scripts)

M2 dimensions reported separately (no weighted aggregation):
  scripts_f1 | go_names_f1 | component_f1 | tags_f1 | inspector_match

Usage:
    uv run python src/evaluation/summary_table.py \\
        --v4  results/replay/20260501-0655/logs \\
        --v2  results/replay/20260501-1353/logs \\
        --ns  results/replay/20260502-0004/logs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NEURIPS   = REPO_ROOT / "results" / "neurips"

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


# ── M1-exec from logs ─────────────────────────────────────────────────────────

def m1_exec_stats(logdir: Path, prefix: str) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for mname, mkey in _MODEL_KEYS.items():
        logs = sorted(logdir.glob(f"{prefix}*{mkey}*.log"))
        if not logs:
            continue
        p = t = 0
        for log in logs:
            text = log.read_text(errors="ignore")
            compile_ok = not _REAL_ERROR.search(text)
            exec_ok    = compile_ok and _AWAKE_OK in text and _UNITY_EXIT in text
            t += 1; p += int(exec_ok)
        stats[mname] = (p, t)
    return stats


# ── M2/M4 from JSONL ──────────────────────────────────────────────────────────

def _model_key(model: str) -> str:
    s = model.lower()
    if "qwen3"    in s: return "Qwen3"
    if "qwen2.5"  in s or "qwen2_5" in s: return "Qwen2.5"
    if "deepseek" in s: return "DeepSeek"
    if "gemma"    in s: return "Gemma4"
    return model


def _cond_key(method: str) -> str:
    if "v4_ir"     in method: return "v4_ir"
    if "v2_ir"     in method: return "v2_ir"
    if "no_schema" in method: return "no_schema"
    return method



def load_jsonl_metrics() -> tuple[
    dict, dict, dict, dict, dict,   # M2: scripts, go_names, comp, tags, insp
    dict, dict, dict, dict, dict, dict,  # M4: win_steps, win_eff, win_conds, lose_steps, lose_eff, lose_conds
]:
    """Return 11 dicts (5 M2 + 6 M4), each {(cond,model): [vals]}.
    Fields collected independently — missing or null values skipped per-field."""
    m2_scripts:    dict[tuple, list] = defaultdict(list)
    m2_go_names:   dict[tuple, list] = defaultdict(list)
    m2_comp:       dict[tuple, list] = defaultdict(list)
    m2_tags:       dict[tuple, list] = defaultdict(list)
    m2_insp:       dict[tuple, list] = defaultdict(list)
    m4_win_steps:  dict[tuple, list] = defaultdict(list)
    m4_win_eff:    dict[tuple, list] = defaultdict(list)
    m4_win_conds:  dict[tuple, list] = defaultdict(list)
    m4_lose_steps: dict[tuple, list] = defaultdict(list)
    m4_lose_eff:   dict[tuple, list] = defaultdict(list)
    m4_lose_conds: dict[tuple, list] = defaultdict(list)

    _field_map = {
        "m2_scripts_f1":      m2_scripts,
        "m2_go_names_f1":     m2_go_names,
        "m2_component_f1":    m2_comp,
        "m2_tags_f1":         m2_tags,
        "m2_inspector_match": m2_insp,
        "m4_win_steps_f1":    m4_win_steps,
        "m4_win_effects_f1":  m4_win_eff,
        "m4_win_conds_f1":    m4_win_conds,
        "m4_lose_steps_f1":   m4_lose_steps,
        "m4_lose_effects_f1": m4_lose_eff,
        "m4_lose_conds_f1":   m4_lose_conds,
    }

    for jf in sorted(NEURIPS.glob("*/evaluation/*.jsonl")):
        with open(jf) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cond  = _cond_key(rec.get("method", ""))
                model = _model_key(rec.get("model", ""))
                key   = (cond, model)

                for field, d in _field_map.items():
                    val = rec.get(field)
                    if val is not None:
                        d[key].append(val)

    return (m2_scripts, m2_go_names, m2_comp, m2_tags, m2_insp,
            m4_win_steps, m4_win_eff, m4_win_conds,
            m4_lose_steps, m4_lose_eff, m4_lose_conds)


# ── Formatting ────────────────────────────────────────────────────────────────

def _pct(p: int, t: int) -> str:
    return f"{p}/{t} ({p*100//t}%)" if t else "—"

def _avg(vals: list) -> str:
    return f"{sum(vals)/len(vals):.3f} (n={len(vals)})" if vals else "—"


# ── Main ──────────────────────────────────────────────────────────────────────

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
_DEFAULT_OUT = REPO_ROOT / "results/neurips/metrics/summary.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="M1/M2/M4 summary table.")
    parser.add_argument("--v4",  type=Path, default=_DEFAULT_V4)
    parser.add_argument("--v2",  type=Path, default=_DEFAULT_V2)
    parser.add_argument("--ns",  type=Path, default=_DEFAULT_NS)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT,
                        help="Write markdown table to this file (default: results/neurips/metrics/summary.md)")
    args = parser.parse_args()

    log_dirs = {
        "v4_ir":    (args.v4, "v4_ir"),
        "v2_ir":    (args.v2, "v2_ir"),
        "no_schema":(args.ns, "no_schema"),
    }

    m1: dict[tuple, tuple[int,int]] = {}
    for cond, (logdir, prefix) in log_dirs.items():
        for mname, stats in m1_exec_stats(logdir, prefix).items():
            m1[(cond, mname)] = stats

    (m2_scripts, m2_go_names, m2_comp, m2_tags, m2_insp,
     m4_win_steps, m4_win_eff, m4_win_conds,
     m4_lose_steps, m4_lose_eff, m4_lose_conds) = load_jsonl_metrics()

    models = list(_MODEL_KEYS)
    lines: list[str] = []

    # Markdown table
    lines.append("| Condition | Model | M1-exec"
                 " | M2 scripts | M2 go_names | M2 comp | M2 tags | M2 insp"
                 " | M4 win_steps | M4 win_eff | M4 win_conds"
                 " | M4 lose_steps | M4 lose_eff | M4 lose_conds |")
    lines.append("|-----------|-------|---------|"
                 "------------|-------------|---------|---------|---------|"
                 "--------------|------------|-------------|"
                 "---------------|------------|---------------|")
    for cond in _CONDITIONS:
        for model in models:
            p, t = m1.get((cond, model), (0, 0))
            key  = (cond, model)
            s_sc  = _avg(m2_scripts.get(key, []))
            s_go  = _avg(m2_go_names.get(key, []))
            s_cp  = _avg(m2_comp.get(key, []))
            s_tg  = _avg(m2_tags.get(key, []))
            s_in  = _avg(m2_insp.get(key, []))
            m4_ws = _avg(m4_win_steps.get(key, []))
            m4_we = _avg(m4_win_eff.get(key, []))
            m4_wc = _avg(m4_win_conds.get(key, []))
            m4_ls = _avg(m4_lose_steps.get(key, []))
            m4_le = _avg(m4_lose_eff.get(key, []))
            m4_lc = _avg(m4_lose_conds.get(key, []))
            has_data = bool(
                t or m2_scripts.get(key) or m4_win_steps.get(key)
            )
            if not has_data:
                continue
            lines.append(
                f"| {cond} | {model} | {_pct(p,t)}"
                f" | {s_sc} | {s_go} | {s_cp} | {s_tg} | {s_in}"
                f" | {m4_ws} | {m4_we} | {m4_wc}"
                f" | {m4_ls} | {m4_le} | {m4_lc} |"
            )

    table = "\n".join(lines)
    print(table)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(table + "\n", encoding="utf-8")
    print(f"\nWritten to: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
