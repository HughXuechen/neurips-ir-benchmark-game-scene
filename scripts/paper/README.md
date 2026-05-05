# Paper-only data wrangling

Scripts that generate paper tables and appendix data from the metrics CSVs / replay logs.
These are NOT part of the core evaluation pipeline (that lives in `src/evaluation/neurips/`).

## Usage

```
uv run python scripts/paper/<script>.py
```

## Scripts

- `build_error_taxonomy.py` — generates Table 4 (compile error taxonomy) and Appendix D data
- `build_ir_excerpt.py` — generates truncated V2/V4 IR JSON excerpts for Appendix J
