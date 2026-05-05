#!/usr/bin/env bash
#SBATCH --job-name=vllm_build_v020
#SBATCH -A <YOUR_ACCOUNT> -p <YOUR_PARTITION>
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/vllm_build_v020_%j.out
#SBATCH --error=logs/vllm_build_v020_%j.err

# Build a clean vLLM v0.20.0 apptainer image.
#
# Why pinned: v0.7.3 (the previously baked image) lacked Gemma4 architecture
# support and had broken DeepSeek-V2-Lite chat-template handling. v0.20.0
# adds Gemma4 + DeepSeek-V2-Lite accuracy fix (#40673) and is built for
# CUDA 13 (matches the cluster driver 13.2).
#
# Why pinned tag (not :latest): reproducibility. Future jobs MUST point at
# vllm_v0.20.0.sif explicitly via VLLM_SIF env override, not at a moving
# vllm_latest.sif.
#
# CPU-only job: apptainer build is I/O + CPU bound, no GPU required.

export PYTHONUNBUFFERED=1
set -euo pipefail

# ====== Paths ======
PROJECT_DIR="${SLURM_SUBMIT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"
mkdir -p logs containers

OUTPUT_SIF="${PROJECT_DIR}/containers/vllm_v0.20.0.sif"
DOCKER_TAG="docker://vllm/vllm-openai:v0.20.0"

if [ -f "$OUTPUT_SIF" ]; then
  echo "[ABORT] $OUTPUT_SIF already exists."
  echo "        Refusing to overwrite. Delete or rename it first if you want to rebuild."
  ls -lh "$OUTPUT_SIF"
  exit 1
fi

# ====== Apptainer tmp / cache ======
# Pin to ${PROJECT_DIR}/.cache/apptainer/ (same convention as the other
# sbatches: HF_HOME, UV_CACHE_DIR, XDG_CACHE_HOME all live under
# ${PROJECT_DIR}/.cache/). PROJECT_DIR resolves to the mimer NFS mount
# (/mimer/NOBACKUP/groups/...) which has 226G free and is reachable from
# every compute node — unlike /tmp, which is per-node local on compute
# (a few GB) and was the cause of the previous build's
# "no space left on device" failure.
export APPTAINER_TMPDIR="${PROJECT_DIR}/.cache/apptainer/tmp-${SLURM_JOB_ID:-$$}"
export APPTAINER_CACHEDIR="${PROJECT_DIR}/.cache/apptainer/cache"
mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"

cleanup() {
  echo "[$(date '+%H:%M:%S')] cleanup: rm -rf $APPTAINER_TMPDIR"
  rm -rf "$APPTAINER_TMPDIR" || true
}
trap cleanup EXIT

# ====== Env modules ======
module purge

# ====== Banner ======
echo "============================================================"
echo "[$(date)] vLLM v0.20.0 apptainer build"
echo "Host:           $(hostname)"
echo "PROJECT_DIR:    $PROJECT_DIR"
echo "Output:         $OUTPUT_SIF"
echo "Source tag:     $DOCKER_TAG"
echo "TMPDIR:         $APPTAINER_TMPDIR"
echo "CACHEDIR:       $APPTAINER_CACHEDIR"
echo "Free /tmp:      $(df -h /tmp                 | tail -1 | awk '{print $4}')   (compute node local; not used)"
echo "Free PROJECT:   $(df -h "$PROJECT_DIR"       | tail -1 | awk '{print $4}')   (shared FS; build dir lives here)"
echo "apptainer:      $(command -v apptainer) $(apptainer --version 2>/dev/null || true)"
echo "============================================================"

# ====== Build ======
echo "[$(date '+%H:%M:%S')] starting apptainer build (typically 30-60 min)"
time apptainer build "$OUTPUT_SIF" "$DOCKER_TAG"
echo "[$(date '+%H:%M:%S')] build complete"

# ====== Sanity ======
echo "------------------------------------------------------------"
echo "[$(date '+%H:%M:%S')] sanity: image size + vLLM/torch versions"
ls -lh "$OUTPUT_SIF"

# vLLM container's default python entrypoint is python3 (no `python`).
apptainer exec "$OUTPUT_SIF" python3 -c "
import vllm, torch, sys
print('python  :', sys.version.split()[0])
print('vllm    :', vllm.__version__)
print('torch   :', torch.__version__)
print('cuda    :', torch.version.cuda)
print('cudnn   :', torch.backends.cudnn.version())
print('build OK.')
"

echo "============================================================"
echo "[$(date)] DONE."
echo ""
echo "Use this image in subsequent jobs by overriding VLLM_SIF, e.g.:"
echo "  VLLM_SIF=$OUTPUT_SIF sbatch scripts/hpc/run_v4_ir_vllm.sbatch"
echo "============================================================"
