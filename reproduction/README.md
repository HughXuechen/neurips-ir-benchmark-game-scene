# Reproduction

This directory contains scripts and expected outputs for reproducing the paper's
main results (Tables 1, 3, 4) from prerecorded replay logs — no Unity or HPC required.

## Prerequisites

1. Clone this repository and install dependencies:
   ```bash
   uv sync
   ```
2. Download the dataset from `<DATASET_URL>` and place it at `./data/`
   (or set `DATA_DIR=/path/to/dataset`).

## Run

```bash
bash reproduction/run_eval_only.sh
```

This script:
1. Sanity-checks that all dataset directories exist.
2. Sets env vars (`V4_LOGS`, `V2_LOGS`, `NS_LOGS`, `V4_JSONL_GLOB`, `V2_JSONL_GLOB`,
   `NS_JSONL_GLOB`) pointing at the dataset.
3. Runs M1/pass@k/McNemar (`src/evaluation/neurips/`).
4. Runs M2/M4 with explicit `--jsonl` globs.
5. Generates the summary table and error taxonomy.

## Compare results

```bash
diff results/neurips/metrics/summary.md reproduction/expected_summary.md
```

The diff should be empty. If numbers differ, check that `DATA_DIR` points to the
correct dataset root.

## Manual invocation

To run individual scripts, source the env file first:
```bash
source reproduction/eval_paths.env
uv run python src/evaluation/neurips/m1_funnel.py
```
