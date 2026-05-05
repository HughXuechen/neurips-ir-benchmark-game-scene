#!/usr/bin/env bash
# Submit all 11 SLURM jobs for the Phase 1 NeurIPS sprint:
#   3 conditions (v4_ir, v2_ir, no_schema) x 4 models = 12 combos,
#   minus 1 incompatible combo (v4_ir + Qwen2.5-Coder-7B, 32K context) = 11 jobs.
#
# Each sbatch file already supports a MODEL env-var override and has
# cross-job skip logic, so re-submitting an already-completed
# (condition, model) pair is harmless — the job spins up briefly and
# exits.
#
# Usage (on HPC):
#   chmod +x scripts/hpc/submit_all_neurips.sh   # one-time
#   git pull && bash scripts/hpc/submit_all_neurips.sh
#
# Results land in: results/neurips/<cond>_<SLURM_JOB_ID>/evaluation/

set -euo pipefail

echo "=========================================================="
echo " Phase 1 NeurIPS sprint — submit 11 SLURM jobs"
echo " 3 conditions x 4 models - 1 incompatible (v4_ir + Qwen2.5-Coder-7B) = 11"
echo "=========================================================="

MODELS=(
  "Qwen/Qwen3-Coder-30B-A3B-Instruct"
  "google/gemma-4-26B-A4B-it"
  "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct"
  "Qwen/Qwen2.5-Coder-7B-Instruct"
)

SBATCH_FILES=(
  "scripts/hpc/run_v4_ir_vllm.sbatch"
  "scripts/hpc/run_v2_ir_vllm.sbatch"
  "scripts/hpc/run_no_schema_vllm.sbatch"
)

submitted=0
for sbatch_file in "${SBATCH_FILES[@]}"; do
  # Derive condition tag from the filename: run_<cond>_vllm.sbatch
  base=$(basename "$sbatch_file" .sbatch)   # run_v4_ir_vllm
  cond=${base#run_}                          # v4_ir_vllm
  cond=${cond%_vllm}                         # v4_ir

  for model in "${MODELS[@]}"; do
    if [[ "$sbatch_file" == *run_v4_ir_vllm.sbatch ]] && \
       [[ "$model" == "Qwen/Qwen2.5-Coder-7B-Instruct" ]]; then
      echo "[SKIP] cond=v4_ir model=$model (32K context insufficient for V4 IR)"
      continue
    fi
    echo "[SUBMIT] cond=${cond} model=${model}"
    MODEL="$model" sbatch "$sbatch_file"
    submitted=$((submitted + 1))
  done
done

echo ""
echo "=========================================================="
echo " Submitted: ${submitted} job(s)"
echo "=========================================================="
echo ""
echo "Current queue:"
squeue -u "$USER" || true
echo ""
echo "Reminder: results land in results/neurips/<cond>_<SLURM_JOB_ID>/"
