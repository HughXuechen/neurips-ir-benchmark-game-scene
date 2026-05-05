#!/usr/bin/env python3
"""
M1 Failure Funnel — compile vs exec pass rates from replay logs.

Implements two metrics:

  M1-compile: log contains no real C# errors (error CS\\d+, excluding CS2001
              stale-ref noise). Equivalent to "code passes Unity compiler."

  M1-exec:    M1-compile AND Awake() executed successfully AND Unity exited
              cleanly (MemoryLeaks marker present). Equivalent to "runtime
              builder ran without crashing."

Failure funnel:
  Generated code
    -> [M1-compile]  compile_fail: real error CS\\d+
    -> [M1-exec]     runtime_fail: Awake crash, NullRef, etc.
    -> [M2]          structure mismatch (separate script)
    -> [M4]          mechanism mismatch (separate script)
    -> Playable

Usage:
    # Compare all three conditions using the standard replay dirs
    uv run python src/evaluation/m1_funnel.py \\
        --v4  results/replay/20260501-0655/logs \\
        --v2  results/replay/20260501-1353/logs \\
        --ns  results/replay/20260502-0004/logs

    # Or pass arbitrary log dirs with labels
    uv run python src/evaluation/m1_funnel.py \\
        --logs v4_ir:results/replay/.../logs v2_ir:... no_schema:...
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Regex: real C# compiler error (not CS2001 stale-ref noise)
_REAL_ERROR_RE = re.compile(r"error CS(?!2001)\d+")

# Markers used to classify a log
_AWAKE_OK    = "GameBuilder.Awake(): OK"
_UNITY_EXIT  = "MemoryLeaks"            # ##utp:{"type":"MemoryLeaks"} — clean exit


def _classify(log: Path) -> tuple[bool, bool]:
    """Return (m1_compile, m1_exec) for a single replay log."""
    text = log.read_text(errors="ignore")
    m1_compile = not _REAL_ERROR_RE.search(text)
    m1_exec    = m1_compile and (_AWAKE_OK in text) and (_UNITY_EXIT in text)
    return m1_compile, m1_exec


_MODEL_KEYS = {
    "Qwen3":   "Qwen3",
    "Qwen2.5": "Qwen2.5",
    "DeepSeek":"deepseek",
    "Gemma4":  "gemma",
}


def analyze_dir(logdir: Path, prefix: str) -> dict[str, dict]:
    """Return per-model stats for one condition."""
    stats: dict[str, dict] = {}
    for mname, mkey in _MODEL_KEYS.items():
        logs = sorted(logdir.glob(f"{prefix}*{mkey}*.log"))
        if not logs:
            continue
        tc = te = pc = pe = 0
        for log in logs:
            mc, me = _classify(log)
            tc += 1; pc += int(mc)
            te += 1; pe += int(me)
        stats[mname] = dict(compile_pass=pc, compile_total=tc,
                            exec_pass=pe, exec_total=te)
    return stats


def _pct(num: int, den: int) -> str:
    if den == 0:
        return "—"
    return f"{num}/{den} ({num*100//den}%)"


def print_table(conditions: list[tuple[str, dict]]) -> None:
    models = list(_MODEL_KEYS)
    cond_labels = [c for c, _ in conditions]

    # Header
    col_w = 20
    header = f"{'Model':<10}"
    for cond in cond_labels:
        header += f"  {'M1-c '+cond:>{col_w}}  {'M1-e '+cond:>{col_w}}"
    print(header)
    print("-" * len(header))

    for model in models:
        row = f"{model:<10}"
        for _, stats in conditions:
            if model not in stats:
                row += f"  {'—':>{col_w}}  {'—':>{col_w}}"
                continue
            s = stats[model]
            row += (f"  {_pct(s['compile_pass'], s['compile_total']):>{col_w}}"
                    f"  {_pct(s['exec_pass'],    s['exec_total']):>{col_w}}")
        print(row)

    # Totals
    print("-" * len(header))
    row = f"{'Total':<10}"
    for _, stats in conditions:
        tc = sum(s['compile_total'] for s in stats.values())
        pc = sum(s['compile_pass']  for s in stats.values())
        te = sum(s['exec_total']    for s in stats.values())
        pe = sum(s['exec_pass']     for s in stats.values())
        row += (f"  {_pct(pc, tc):>{col_w}}"
                f"  {_pct(pe, te):>{col_w}}")
    print(row)


REPO_ROOT   = Path(__file__).resolve().parents[3]


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
_DEFAULT_V4  = REPO_ROOT / _EVAL_ENV.get("V4_LOGS", "results/replay/20260501-0655/logs")
_DEFAULT_V2  = REPO_ROOT / _EVAL_ENV.get("V2_LOGS", "results/replay/20260501-1353/logs")
_DEFAULT_NS  = REPO_ROOT / _EVAL_ENV.get("NS_LOGS", "results/replay/20260502-0004/logs")
_DEFAULT_OUT = REPO_ROOT / "results/neurips/metrics/m1_funnel.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 compile/exec funnel by condition.")
    parser.add_argument("--v4",  type=Path, default=_DEFAULT_V4)
    parser.add_argument("--v2",  type=Path, default=_DEFAULT_V2)
    parser.add_argument("--ns",  type=Path, default=_DEFAULT_NS)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--logs", nargs="*", metavar="LABEL:PATH",
                        help="Arbitrary conditions as label:path pairs")
    args = parser.parse_args()

    conditions: list[tuple[str, dict]] = []
    conditions.append(("v4_ir",     analyze_dir(args.v4, "v4_ir")))
    conditions.append(("v2_ir",     analyze_dir(args.v2, "v2_ir")))
    conditions.append(("no_schema", analyze_dir(args.ns, "no_schema")))
    for entry in (args.logs or []):
        label, path = entry.split(":", 1)
        conditions.append((label, analyze_dir(Path(path), label.replace("-", "_"))))

    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_table(conditions)
    output = buf.getvalue()
    print(output, end="")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8")
    print(f"Written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
