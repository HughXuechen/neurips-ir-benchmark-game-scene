#!/usr/bin/env bash
#SBATCH --job-name=no_schema_vllm
#SBATCH -A <YOUR_ACCOUNT> -p <YOUR_PARTITION>
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --time=12:00:00
#SBATCH --gpus-per-node=<GPU_TYPE>:1
#SBATCH --output=logs/no_schema_%j.out
#SBATCH --error=logs/no_schema_%j.err

export PYTHONUNBUFFERED=1
set -euo pipefail

# ====== Paths ======
PROJECT_DIR="${SLURM_SUBMIT_DIR:-$(pwd)}"
VLLM_SIF="${VLLM_SIF:-${PROJECT_DIR}/containers/vllm_v0.20.0.sif}"

cd "$PROJECT_DIR"
mkdir -p logs containers

# ====== Env ======
export HF_HOME="${PROJECT_DIR}/.cache/huggingface"
export HUGGINGFACE_HUB_CACHE="${HF_HOME}/hub"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
export UV_CACHE_DIR="${PROJECT_DIR}/.cache/uv"
export XDG_CACHE_HOME="${PROJECT_DIR}/.cache/xdg"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export TMPDIR="/tmp/vllm_${SLURM_JOB_ID:-$$}"
export TEMP="$TMPDIR"
export TMP="$TMPDIR"
export TRITON_CACHE_DIR="$TMPDIR/triton"
export TORCHINDUCTOR_CACHE_DIR="$TMPDIR/torchinductor"
export TORCH_INDUCTOR_CACHE_DIR="$TMPDIR/torchinductor"
export INDUCTOR_CACHE_DIR="$TMPDIR/torchinductor"
mkdir -p "$TMPDIR" "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR"

mkdir -p "$HF_HOME" "$HUGGINGFACE_HUB_CACHE" "$TRANSFORMERS_CACHE" \
         "$UV_CACHE_DIR" "$XDG_CACHE_HOME"

if [ -f "${HOME}/.secrets" ]; then source "${HOME}/.secrets"; fi

# ====== Require pre-built vLLM container ======
# Do NOT auto-pull: docker://vllm/vllm-openai:latest is a moving tag and was
# the root cause of the v0.7.3 / Gemma4 / DeepSeek-V2-Lite breakage. Build the
# pinned image explicitly with scripts/hpc/build_vllm_v020.sbatch.
if [ ! -f "$VLLM_SIF" ]; then
  echo "[ABORT] vLLM image not found: $VLLM_SIF"
  echo "        Build it first:  sbatch scripts/hpc/build_vllm_v020.sbatch"
  echo "        Or override:     VLLM_SIF=/path/to/your.sif sbatch <this script>"
  exit 1
fi

# ====== Env modules ======
module purge
module load uv

# ====== Activate venv ======
if [ ! -d "${PROJECT_DIR}/.venv" ]; then
  echo "[INFO] Creating venv"
  uv venv "${PROJECT_DIR}/.venv"
fi
source "${PROJECT_DIR}/.venv/bin/activate"

# ====== Configuration ======
COND="no_schema"
MODELS=(
  "Qwen/Qwen3-Coder-30B-A3B-Instruct"
  "google/gemma-4-26B-A4B-it"
  "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct"
  "Qwen/Qwen2.5-Coder-7B-Instruct"
)
# Allow single-model override for parallel submission:
#   MODEL="..." sbatch scripts/hpc/run_no_schema_vllm.sbatch
if [ -n "${MODEL:-}" ]; then
  echo "[INFO] MODEL override: $MODEL"
  MODELS=("$MODEL")
fi
SEEDS=(0 1 2)

# No-schema prompts are short; max-tokens raised to match V4 output length
MODEL_ARGS=(--max-model-len 32768 --max-num-seqs 1 --gpu-memory-utilization 0.95)

RESULTS_DIR="results/neurips/no_schema_${SLURM_JOB_ID:-local}"
mkdir -p "$RESULTS_DIR/evaluation"

echo "===== No-Schema Baseline ====="
echo "Host: $(hostname) | Start: $(date)"
echo "Models: ${MODELS[*]}"
echo "Seeds: ${SEEDS[*]}"
echo "Results: $RESULTS_DIR"
echo "=============================="

# ====== NL → C# (no IR) ======
for MODEL in "${MODELS[@]}"; do
  for SEED in "${SEEDS[@]}"; do
    OUT_FILE="$RESULTS_DIR/evaluation/${COND}_${MODEL//\//_}_seed${SEED}.jsonl"
    # In-job skip (resume support)
    if [ -s "$OUT_FILE" ]; then
      echo "[SKIP] Exists: $OUT_FILE"
      continue
    fi
    # Cross-job skip: look for any prior job dir that has this exact result
    EXISTING=$(ls -1 results/neurips/${COND}_*/evaluation/${COND}_${MODEL//\//_}_seed${SEED}.jsonl 2>/dev/null | head -n1 || true)
    if [ -n "$EXISTING" ] && [ -s "$EXISTING" ]; then
      echo "[SKIP] Already done in another job dir: $EXISTING"
      continue
    fi
    echo "[RUN] model=$MODEL seed=$SEED"
    apptainer exec --nv "$VLLM_SIF" python3 src/llm_batch/run_no_schema.py \
      --backend vllm \
      --model "$MODEL" \
      --seed "$SEED" \
      --num-runs 1 \
      --max-tokens 8192 \
      --out "$OUT_FILE" \
      "${MODEL_ARGS[@]}"
  done
done

echo ""
echo "=== Done: $(date) ==="
echo "Expected: ${#MODELS[@]} models x ${#SEEDS[@]} seeds = $((${#MODELS[@]} * ${#SEEDS[@]})) JSONL files"
ls -la "$RESULTS_DIR/evaluation/"
