#!/usr/bin/env bash
# Reproduce Tables 1, 3, 4 from prerecorded replay logs (no Unity / HPC required).
# Assumes the dataset has been downloaded and placed at $DATA_DIR.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO=$(realpath "$SCRIPT_DIR/..")
DATA_DIR=${DATA_DIR:-$REPO/data}

# 1. Sanity check
for d in patterns ground_truth ir/v2 ir/v4 generation_outputs replay_logs; do
  [ -d "$DATA_DIR/$d" ] || { echo "FATAL: missing $DATA_DIR/$d" >&2; exit 2; }
done

# 2. Point all eval scripts at the dataset via env vars
#    (src/evaluation/neurips/*.py and scripts/paper/*.py both honor these)
export V4_LOGS="$DATA_DIR/replay_logs/full_scene"
export V2_LOGS="$DATA_DIR/replay_logs/behavior_only"
export NS_LOGS="$DATA_DIR/replay_logs/no_schema"
export V4_JSONL_GLOB="$DATA_DIR/generation_outputs/v4_ir/*.jsonl"
export V2_JSONL_GLOB="$DATA_DIR/generation_outputs/v2_ir/*.jsonl"
export NS_JSONL_GLOB="$DATA_DIR/generation_outputs/no_schema/*.jsonl"

# 3. M1 / pass@k / McNemar (default flags use the env vars above)
uv run python "$REPO/src/evaluation/neurips/m1_funnel.py"
uv run python "$REPO/src/evaluation/neurips/pass_at_k.py"
uv run python "$REPO/src/evaluation/neurips/statistical_tests.py"

# 4. M2 / M4 (need explicit --jsonl glob)
uv run python "$REPO/src/evaluation/neurips/m2_v2_structure_score.py" \
    --jsonl $V4_JSONL_GLOB $V2_JSONL_GLOB $NS_JSONL_GLOB
uv run python "$REPO/src/evaluation/neurips/m4_mechanism_adherence.py" \
    --jsonl $V4_JSONL_GLOB $V2_JSONL_GLOB $NS_JSONL_GLOB

# 5. Summary + paper Tables
uv run python "$REPO/src/evaluation/neurips/summary_table.py"
uv run python "$REPO/scripts/paper/build_error_taxonomy.py"

echo "Done. Compare results/neurips/metrics/summary.md to $SCRIPT_DIR/expected_summary.md"
