# Metrics Extraction Reference

**Last updated:** 2026-05-02  
**Scope:** M1 / M2 / M4 evaluation metrics — field extraction rules, GT sources, known skips / assumptions. Does not cover story framing or paper writing.

---

## 0. Conventions

### Multiset F1 (used by M2)
`_f1(gt: Counter, gen: Counter)` — `m2_v2_structure_score.py:43`

```
precision  = |gt ∩ gen| / sum(gen values)
recall     = |gt ∩ gen| / sum(gt values)
F1         = 2 * P * R / (P + R)
```
Both empty → 1.0. One empty → 0.0. (Symmetric with multiset intersection.)

### Set F1 (used by M4)
`_f1_sets(gt: set, gen: set)` — `m4_mechanism_adherence.py:47`

```
precision  = |gt ∩ gen| / |gen|
recall     = |gt ∩ gen| / |gt|
F1         = 2 * P * R / (P + R)
```
Both empty → **1.0** (perfect match by convention).  
One empty → **0.0** (total miss in either direction).

### n semantics
| Metric | Denominator n |
|--------|--------------|
| M1 | All replay log files in the directory |
| M2 | M1-exec passed runs only (gen_parsed.json exists) |
| M4 | All records in JSONL (no compile requirement) |

M2's n < 78 per (model, condition) because runs that failed M1-exec have no parsed scene. The `n=` value printed in summary_table.py is this reduced denominator.

---

## 1. M1

### 1.1 M1-compile

**Definition:** A run passes M1-compile if its replay log contains **no real C# compiler errors**.

**Regex:** `re.compile(r"error CS(?!2001)\d+")` — `m1_funnel.py:42`

**CS2001 exclusion:** CS2001 is a stale-file-reference warning emitted when Unity re-imports an unchanged asset. It is not a code error. The negative lookahead `(?!2001)` filters it out.

**GT source:** N/A — M1 is computed directly from replay log text.

### 1.2 M1-exec

**Definition:** A run passes M1-exec if it passes M1-compile AND both of the following markers appear in the log:

| Marker string | Variable | Line |
|---|---|---|
| `GameBuilder.Awake(): OK` | `_AWAKE_OK` | `m1_funnel.py:45` |
| `MemoryLeaks` | `_UNITY_EXIT` | `m1_funnel.py:46` |

The `MemoryLeaks` marker is the JSON prefix `##utp:{"type":"MemoryLeaks"}` emitted by the Unity Test Protocol on clean exit.

### 1.3 Marker sources

- `GameBuilder.Awake(): OK` — printed by the **BatchRunner** script inside Unity when the `GameBuilder.Awake()` method completes without throwing. Absence means the scene failed to initialize at runtime.
- `MemoryLeaks` — emitted by **Unity's built-in Test Protocol** on clean process exit. Absence means Unity crashed or was killed before finishing.

**Output:** `results/neurips/metrics/m1_funnel.md`

---

## 2. M2 — Five Structure Dimensions

**GT directory:** `data/processed/scene_analysis/`  
**Gen directory:** `results/unity_generated/<model>/<pattern>/<method>/<run_id>/gen_parsed.json`  
**Script:** `src/evaluation/neurips/m2_v2_structure_score.py`

M2 is **only computed on runs that have a `gen_parsed.json`** (i.e., M1-exec passed). Runs without it are silently skipped at `m2_v2_structure_score.py:329`. The `n=` in summary output is the M1-exec subset count.

### 2.1 scripts\_f1

| | |
|---|---|
| **GT file** | `<pid>_manifest.json` |
| **GT field** | `manifest["scripts"].keys()` (Counter) — `extract_gt_class_names()` L66 |
| **Gen source** | `output_code` field in JSONL |
| **Gen extraction** | `re.findall(r"public\s+class\s+(\w+)", output_code)` → Counter — `extract_gen_class_names()` L79 |
| **Comparison** | Multiset F1 (`_f1`) |
| **Skip** | `SceneBuilder` class excluded from gen (editor-only boilerplate) — L80 |

### 2.2 go\_names\_f1

| | |
|---|---|
| **GT file** | `<pid>_parsed.json` |
| **GT field** | `blocksByType.GameObject[*].data.GameObject.m_Name` — `extract_go_names()` L106 |
| **Gen source** | `gen_parsed.json` (same schema) |
| **Gen extraction** | Same function on gen_parsed |
| **Comparison** | Multiset F1 |
| **Skip** | Empty name strings skipped — L111 |

### 2.3 component\_f1

| | |
|---|---|
| **GT file** | `<pid>_parsed.json` |
| **GT field** | `blocksByType` — count of blocks per type — `extract_component_types()` L87 |
| **Gen source** | `gen_parsed.json` |
| **Gen extraction** | Same function |
| **Comparison** | Multiset F1 |
| **Skip** | Four Unity settings blocks excluded (not gameplay components): `OcclusionCullingSettings`, `RenderSettings`, `LightmapSettings`, `NavMeshSettings` — L89 |

### 2.4 tags\_f1

| | |
|---|---|
| **GT file** | `<pid>_parsed.json` |
| **GT field** | `blocksByType.GameObject[*].data.GameObject.m_TagString` where value ≠ `"Untagged"` — `extract_tags()` L97 |
| **Gen source** | `gen_parsed.json` |
| **Gen extraction** | Same function |
| **Comparison** | Multiset F1 |
| **Skip** | `"Untagged"` tag excluded (default Unity tag, not meaningful) — L101 |

### 2.5 inspector\_match

| | |
|---|---|
| **GT file** | `<pid>_extraction.json` |
| **GT field** | `inspector_values.<ClassName>.fields` — scalar values only (`int`, `float`, `bool`, `str`) — `extract_gt_inspector_values()` L116 |
| **Gen source** | `output_code` field in JSONL |
| **Gen extraction** | Regex: `var (\w+) = \w+\.AddComponent<(\w+)>()` to map variable→class, then `var.field = value;` to find assignments — `extract_gen_inspector_values()` L136 |
| **Comparison** | `matched / total` GT scalar fields — `compute_inspector_match()` L176 |
| **Float tolerance** | `abs(gt - gen) <= 0.01` for float values — `_values_match()` |
| **Assumptions / skip** | Only `var X = AddComponent<C>()` pattern captured; `gameObject.GetComponent<C>().field = v` and other assignment patterns are missed. Only scalar fields compared (no fileID refs, no arrays). |

### 2.6 Data observations

- **inspector\_match = 0.0 is not the same as "missing"**: 0.0 means GT has inspector fields but the LLM's generated code matched none of them. A missing value (`—` in summary) means no records were found for that (condition, model) pair.
- **inspector\_match is consistently 0.0** in current data. This reflects that LLM-generated code rarely uses the `var X = AddComponent<C>()` assignment pattern. The GT values are present; the gen extraction returns nothing.
- **M2 skips ~65 of 78 runs per no\_schema condition** — these runs failed M1-exec (no `gen_parsed.json`). The no\_schema condition suppresses structured IR, so most generated code does not compile or initialize correctly.

**Output:** `results/neurips/metrics/m2/m2_v2_per_run.csv`, `m2_v2_by_pattern.csv`, `m2_v2_detail.json`

---

## 3. M4 — Three Dimensions × Win / Lose

**GT directory:** `data/processed/scene_analysis/`  
**Script:** `src/evaluation/neurips/m4_mechanism_adherence.py`  
**Important:** M4 requires no compiled scene — it runs on `output_code` directly. n = all records in JSONL.

### 3.1 condition\_path.json schema

Real example from `data/processed/scene_analysis/1_Ownership_condition_path.json`:

```json
{
  "pattern": "1_Ownership",
  "condition_path": {
    "win": [
      {
        "step": "counter_update",
        "actor_class": "ChangeColor",
        "event": "OnTriggerEnter2D",
        "conditions": ["col.gameObject == target && !colorChange"],
        "effect": "GoalManager.instance.currentCount++",
        "evidence": "data/raw/unity/PatternsUnityCode/Assets/Scripts/ChangeColor.cs:33",
        "method_body": "..."
      }
    ],
    "lose": []
  },
  "scripts_analyzed": 7
}
```

Each step: `actor_class` (string), `event` (Unity message name), `conditions` (array of condition expression strings), `effect` (string), `evidence` (file:line), `method_body` (string).

`lose` may be an empty array if the pattern has no lose condition path.

### 3.2 steps\_f1

| | |
|---|---|
| **GT** | `condition_path.{win,lose}[*]` — set of `"{actor_class}.{event}"` signatures — `extract_step_signature()` L143 |
| **Gen extraction** | `extract_classes_from_code()` L62 → temp files → `analyze_cs_file()` → `trace_condition_paths()` |
| **Comparison** | Set F1 (`_f1_sets`) on step-signature sets |

### 3.3 effects\_f1

| | |
|---|---|
| **GT** | `condition_path.{win,lose}[*].effect` strings |
| **Gen extraction** | Same tracing pipeline |
| **Comparison** | Set F1 on effect string sets — `compare_paths()` L153 |

### 3.4 conditions\_f1

| | |
|---|---|
| **GT** | `condition_path.{win,lose}[*].conditions[]` — union of all condition expression strings per path |
| **Gen extraction** | Same tracing pipeline |
| **Comparison** | Set F1 on condition-expression sets — `compare_paths()` L156 |

### 3.5 Win / lose split and null handling

Each dimension is computed **separately for win and lose paths**, yielding 6 fields total:  
`m4_win_steps_f1`, `m4_win_effects_f1`, `m4_win_conds_f1`,  
`m4_lose_steps_f1`, `m4_lose_effects_f1`, `m4_lose_conds_f1`

If **GT has no lose path** (`condition_path.lose == []`), all three `m4_lose_*` fields are written as `null` (Python `None` → JSON `null`). This is intentional — `_f1_sets({}, {})` would return 1.0, which would pollute the mean. Null values are excluded from mean calculation in summary_table.py.

`compute_m4()` implements this — `m4_mechanism_adherence.py:178`.

### 3.6 SceneBuilder skip

`extract_classes_from_code()` (L76) skips any class named `SceneBuilder`. This is a Unity Editor scaffold class generated by the pipeline and not part of the gameplay logic.

### 3.7 Code extraction method

`extract_classes_from_code()` uses **brace-depth counting** to isolate class bodies from the generated C# string. Known blindspot: string literals and comments containing `{` or `}` can throw off the depth count, potentially misattributing code to the wrong class.

**tmpdir constraint:** `trace_gen_condition_path()` writes temp `.cs` files to `ROOT/.tmp_m4` (L122). This directory is not safe for concurrent M4 runs; M4 must be run serially.

**Output:** `results/neurips/metrics/m4/m4_per_run.csv`, `m4_by_pattern.csv`, `m4_detail.json`

---

## 4. pass@k and statistical\_tests

### 4.1 pass@k

**Estimator:** Chen et al. (2021) unbiased estimator — `pass_at_k.py:89`

```
pass@k = 1 - C(n-c, k) / C(n, k)
```
where `n` = seeds per (model, pattern), `c` = seeds that pass M1-exec.

**Aggregation:** Computed per (condition, model, pattern), then **macro-averaged across patterns** — `pass_at_k.py:133`. Current data has `n=3` seeds per (model, pattern).

**pattern\_id extraction from logs:** `_pattern_from_log()` (L74) reads `pattern=(\S+)` from log content. Coverage verified: 234/234 V4, 312/312 V2, 310/310 NS logs contain this marker.

**Output:** `results/neurips/metrics/pass_at_k.csv`, `pass_at_k.md`

### 4.2 McNemar exact test + any-pass aggregation

**Script:** `src/evaluation/neurips/statistical_tests.py`

**Pairing unit:** Each (model, pattern) pair is one observation. Conditions are compared pairwise (v4\_ir vs v2\_ir, v4\_ir vs no\_schema, v2\_ir vs no\_schema).

**Aggregation across seeds (any-pass):** For a given (model, pattern), the outcome is `1` if **any** of the 3 seeds passes M1-exec, else `0` — `statistical_tests.py:142-143`. This is not majority vote.

**Test:** Two-sided exact McNemar (binomial sign test) — `mcnemar_exact()` L91. Also reports odds ratio with 95% CI and Cohen's h effect size.

**Output:** `results/neurips/metrics/statistical_tests.csv`, `statistical_tests.md`

---

## 5. Known Blindspots and Limitations

| Limitation | Where | Detail |
|---|---|---|
| inspector\_match under-counts | `m2_v2_structure_score.py:147` | Only `var X = AddComponent<C>()` assignment pattern captured. `GetComponent<C>()`, field initialization in constructors, and other patterns are missed. |
| M4 brace counting | `m4_mechanism_adherence.py:80,93` | Class body extraction uses `{`/`}` depth counting. String literals and comments with braces can misattribute code. |
| M4 serial execution | `m4_mechanism_adherence.py:122` | `tmpdir = ROOT / ".tmp_m4"` is a single shared directory; concurrent M4 runs will conflict. |
| M2 n < 78 | `m2_v2_structure_score.py:329` | Records without `gen_parsed.json` are skipped silently. n printed in summary is M1-exec subset. |
| no\_schema M4 = 0.0 | Design | no\_schema has no structured IR; `trace_condition_paths` finds no valid condition paths in unstructured code. This is expected and is a key finding (compile ≠ playable). |
| pattern= marker required | `pass_at_k.py:79`, `statistical_tests.py:77` | If marker is absent, pattern falls to `"unknown"`, collapsing all unknown seeds into one pseudo-pattern. Coverage is 100% in current data (verified 2026-05-02). |

### Path convention for this directory

All scripts in `src/evaluation/neurips/` live three levels below repo root:

```
repo_root/src/evaluation/neurips/<file>.py
parents[0] = src/evaluation/neurips
parents[1] = src/evaluation
parents[2] = src
parents[3] = repo_root   ← use this
```

Use `Path(__file__).resolve().parents[3]` to reach repo root. Using `parents[2]` points to `src/` and silently breaks all GT/gen path lookups (scripts run without error but skip all records).
