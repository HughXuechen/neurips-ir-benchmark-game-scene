#!/usr/bin/env bash
#SBATCH --job-name=gen_prompts
#SBATCH -A <YOUR_ACCOUNT> -p <YOUR_PARTITION>
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:10:00
#SBATCH --output=logs/gen_prompts_%j.out
#SBATCH --error=logs/gen_prompts_%j.err

set -euo pipefail

PROJECT_DIR="${SLURM_SUBMIT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"
mkdir -p logs

# ====== Env — keep caches off home directory ======
export UV_CACHE_DIR="${PROJECT_DIR}/.cache/uv"
export XDG_CACHE_HOME="${PROJECT_DIR}/.cache/xdg"
mkdir -p "$UV_CACHE_DIR" "$XDG_CACHE_HOME"

module purge
module load uv

if [ ! -d "${PROJECT_DIR}/.venv" ]; then
  uv venv "${PROJECT_DIR}/.venv"
fi
source "${PROJECT_DIR}/.venv/bin/activate"

echo "=== Generating prompts: $(date) ==="
uv run python src/prompts/generate_prompts.py
echo "=== Done: $(date) ==="
ls results/prompts/ | wc -l
