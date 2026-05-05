# Scene-Level Grounding Benchmark — Code

Anonymous code release for the NeurIPS 2026 Evaluation & Datasets submission
"Scene-Level Grounding for LLM Code Generation: A Multi-Granularity IR
Benchmark for Executable Game Scene Synthesis".

## Quickstart (reproduce Tables 1, 3, 4 from prerecorded logs, no Unity needed)

```bash
git clone <this-repo>
cd <repo>
uv sync
# Download dataset from https://huggingface.co/datasets/anon-neurips-2026-0502/scene-level-grounding-benchmark and unpack as ./data/
bash reproduction/run_eval_only.sh
# Compare results/neurips/metrics/summary.md to reproduction/expected_summary.md
```

## Full reproduction (HPC + local Unity)

1. **Generate** (HPC, vLLM, ~24h on 4 H100):
   `bash scripts/hpc/submit_all_neurips.sh`
2. **Replay** (local, Unity 2022.2.23f1, ~6h):
   `bash run_batch_replay.sh`
3. **Evaluate**:
   `bash src/evaluation/neurips/run_eval_pipeline.sh`

## Repository layout

```
src/evaluation/neurips/   Evaluation harness (M1/M2/M4 metrics, pass@k, McNemar)
src/scene_analysis/       Ground-truth IR extraction pipeline from Unity scenes
src/ir_schema/            V2 (behavior-only) and V4 (full-scene) IR schema docs
src/prompts/              Prompt templates for all three conditions
scripts/paper/            Paper table generation (error taxonomy, summary)
scripts/hpc/              HPC job submission scripts (account/partition redacted)
ai_command/               C# Unity replay controller
docs/                     Metrics extraction documentation
reproduction/             Reproduction scripts and expected outputs
```

## Dataset

The patterns, ground truth, IRs, and 858 generation outputs are released
separately on HuggingFace at `https://huggingface.co/datasets/anon-neurips-2026-0502/scene-level-grounding-benchmark`; see `DATASET.md`.

## Requirements

- Python 3.12+, [uv](https://github.com/astral-sh/uv)
- For full reproduction: Unity 2022.2.23f1, SLURM cluster with GPU nodes

## License

Apache-2.0 (code) / CC-BY-4.0 (data, see dataset repo)
