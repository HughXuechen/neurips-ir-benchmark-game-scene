"""Build error taxonomy tables for §5.4 (Table 4) and Appendix D.

Inputs (resolved via env vars > eval_paths.env > timestamp defaults):
  NS_LOGS  → no_schema replay logs
  V2_LOGS  → behavior-only replay logs
  V4_LOGS  → full-scene replay logs

Output: stdout (LaTeX-ready cells for Table 4 and Appendix D).
Only the 858 evaluation-attempt logs are used; pilot / development
replay directories are excluded.

To reproduce on the anonymous-dataset staging dir, point env vars at it:
    NS_LOGS=local_doc/neurips/anonymous-dataset/replay_logs/no_schema \
    V2_LOGS=local_doc/neurips/anonymous-dataset/replay_logs/behavior_only \
    V4_LOGS=local_doc/neurips/anonymous-dataset/replay_logs/full_scene \
    uv run python scripts/paper/build_error_taxonomy.py
Or set them in eval_paths.env. Both invocations must produce byte-perfect
identical Table 4 / Appendix D.
"""

import os
import re
import sys
from pathlib import Path
from collections import Counter

BASE = Path(__file__).resolve().parents[2]


def _read_eval_env() -> dict:
    p = BASE / "local_doc/agent/eval_paths.env"
    out: dict = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


_env_file = _read_eval_env()


def _ev(key, default):
    return os.environ.get(key) or _env_file.get(key) or default


REPLAY_DIRS = {
    'no_schema':     BASE / _ev("NS_LOGS", "results/replay/20260502-0004/logs"),
    'behavior_only': BASE / _ev("V2_LOGS", "results/replay/20260501-1353/logs"),
    'full_scene':    BASE / _ev("V4_LOGS", "results/replay/20260501-0655/logs"),
}

for cond, path in REPLAY_DIRS.items():
    if not path.is_dir():
        print(f"FATAL: missing replay dir for {cond}: {path}", file=sys.stderr)
        sys.exit(2)

ERR_RE = re.compile(r'error (CS\d+)')
EXCLUDE = {'CS2001'}  # stale-reference editor message, excluded per eval protocol

# 1. Aggregate count per error code, per condition
counts = {cond: Counter() for cond in REPLAY_DIRS}
for cond, logdir in REPLAY_DIRS.items():
    for log in logdir.glob('*.log'):
        text = log.read_text(errors='ignore')
        for m in ERR_RE.finditer(text):
            if m.group(1) not in EXCLUDE:
                counts[cond][m.group(1)] += 1

# 2. Top 10 codes by grand total
all_total: Counter = Counter()
for cond_counts in counts.values():
    all_total.update(cond_counts)
top10 = [code for code, _ in all_total.most_common(10)]
grand_total = sum(all_total.values())

# 3. Print Table 4 (§5.4) — total column only
print("=" * 60)
print("Table 4 (§5.4) — total occurrences across 858 attempts")
print("=" * 60)
print(f"{'Code':<8}  {'Total':>8}  {'Meaning'}")
meanings = {
    'CS1003': 'Syntax error, token expected',
    'CS1001': 'Identifier expected',
    'CS1002': '; expected',
    'CS1031': 'Type expected',
    'CS1026': ') expected',
    'CS8124': 'Tuple must contain at least two elements',
    'CS0246': 'Type/namespace name not found',
    'CS0122': 'Inaccessible due to protection level',
    'CS1029': '#error directive (sanitizer fallback)',
    'CS1519': 'Invalid token in class/struct/interface body',
}
top4_total = sum(all_total[c] for c in top10[:4])
print(f"Grand total errors: {grand_total}")
print(f"Top-4 fraction: {top4_total}/{grand_total} = {top4_total/grand_total:.1%}")
print()
for code in top10:
    total = all_total[code]
    print(f"  {code:<8}  {total:>8}  {meanings.get(code, '')}")

# 4. Print Appendix D — 3-column breakdown (no_schema / behavior_only / full_scene)
print()
print("=" * 60)
print("Appendix D — per-condition breakdown")
print("=" * 60)
print(f"{'Code':<8}  {'No-schema':>10}  {'Behavior-only':>14}  {'Full-scene':>12}")
for code in top10:
    ns = counts['no_schema'][code]
    bo = counts['behavior_only'][code]
    fs = counts['full_scene'][code]
    print(f"  {code:<8}  {ns:>10}  {bo:>14}  {fs:>12}")
