#!/usr/bin/env bash
# Full NeurIPS evaluation pipeline.
# Run this after all three replay jobs are complete.
#
# Prerequisites: edit local_doc/agent/eval_paths.env if your job IDs differ.
#
# Usage:
#   bash src/evaluation/neurips/run_eval_pipeline.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# shellcheck source=local_doc/agent/eval_paths.env
source "$REPO_ROOT/local_doc/agent/eval_paths.env"

echo "========================================"
echo "NeurIPS Evaluation Pipeline"
echo "========================================"

# ── Step 1: M1-compile + M1-exec ─────────────────────────────────────────────
# Reads replay logs. Detects:
#   M1-compile: no real error CS\d+ in log (excludes CS2001 stale-ref noise)
#   M1-exec:    compile pass + "GameBuilder.Awake(): OK" + "MemoryLeaks" marker
# Outputs: results/neurips/metrics/m1_funnel.md + .csv
echo ""
echo "[1/6] M1 compile + exec (from replay logs)"
uv run python "$SCRIPT_DIR/m1_funnel.py"

# ── Step 2: Parse generated scenes (M2 prerequisite) ─────────────────────────
# Reads: results/unity_generated/**/scene.unity
#   (BatchRunner exports these during replay for M1-exec-passing records)
# Outputs: gen_parsed.json next to each scene.unity
echo ""
echo "[2/6] Parse exported scenes → gen_parsed.json"
uv run python "$SCRIPT_DIR/parse_generated_scenes.py" --force

# ── Step 3: M2 Structure Score ────────────────────────────────────────────────
# Reads: jsonl files (run_id, model, pattern_id) + gen_parsed.json + GT parsed
# Patches m2_* fields into jsonl (only records with an exported scene get a score)
# Outputs: results/neurips/metrics/m2_v2_per_run.csv, m2_v2_by_pattern.csv
echo ""
echo "[3/6] M2 structure score"
uv run python "$SCRIPT_DIR/m2_v2_structure_score.py" \
  --jsonl $V4_JSONL_GLOB \
          $V2_JSONL_GLOB \
          $NS_JSONL_GLOB

# ── Step 4: M4 Mechanism Adherence ───────────────────────────────────────────
# Reads: output_code from jsonl (static analysis — no scene needed)
#        + ground truth condition_path from data/processed/scene_analysis/
# Patches m4_* fields into jsonl for every record with output_code
# Outputs: results/neurips/metrics/m4_per_run.csv, m4_by_pattern.csv
echo ""
echo "[4/6] M4 mechanism adherence"
uv run python "$SCRIPT_DIR/m4_mechanism_adherence.py" \
  --jsonl $V4_JSONL_GLOB \
          $V2_JSONL_GLOB \
          $NS_JSONL_GLOB

# ── Step 5: Summary table ─────────────────────────────────────────────────────
# Reads: replay logs (M1) + patched jsonl (M2/M4 fields)
# Outputs: results/neurips/metrics/summary_m1_m2_m4.md
echo ""
echo "[5/6] Summary table (M1 + M2 + M4)"
uv run python "$SCRIPT_DIR/summary_table.py"

# ── Step 6: pass@k + statistical tests ───────────────────────────────────────
# Both read only replay logs (M1-exec per pattern per seed)
# Outputs: results/neurips/metrics/pass_at_k.md, statistical_tests.md
echo ""
echo "[6/6] pass@k + statistical tests"
uv run python "$SCRIPT_DIR/pass_at_k.py"
uv run python "$SCRIPT_DIR/statistical_tests.py"

echo ""
echo "========================================"
echo "Done. Results in results/neurips/metrics/"
ls results/neurips/metrics/*.md
echo "========================================"
