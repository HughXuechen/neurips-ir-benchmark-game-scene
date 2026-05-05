# IR Iteration History

Timeline of schema changes from initial draft to current frozen version.

| # | Iteration | What Changed | Why | Impact on Generation / Evaluation |
|---|-----------|-------------|-----|-----------------------------------|
| 1 | **IR v0 static draft** | Defined top-level fields: `scene`, `objects`, `scripts`, `params`, `links`, `rules`. | Need a minimal structured representation between GDD constraints and Unity code generation. | Established the baseline schema all pipeline stages consume. |
| 2 | **MVP narrowing** | Deferred `params` extraction; pipeline operates on `objects`, `scripts`, `links`, `rules` only. | `params` requires GUID resolution (scene -> prefab -> script -> `.cs`), blocking the initial pipeline. | Unblocked end-to-end generation without serialized-field extraction. `params` emitted as `{}`. |
| 3 | **Runtime extension** | Added `PrefabInstance` / `PrefabAsset` object types, runtime spawn/instantiate behavior, script-defined rules, and `runtime_params` field. | Static `.unity` parsing alone misses prefab-driven gameplay. Core behavior often emerges from Prefab + runtime spawn + script logic. | IR now captures the actual gameplay loop; generation can reason about spawned entities and runtime config. |
| 4 | **Per-instance script constraint** | `scripts[].object_id` must reference a real `objects[].id`. No implicit aggregate placeholders (e.g. `circle_all`). | Aggregate placeholders created ambiguous references that could not be resolved during code generation or evaluation. | Enforces 1:1 script-to-object binding; evaluation can validate referential integrity automatically. |
| 5 | **Evidence-aware semantics** | Conditional relation labels (e.g. `can_trigger_game_win_if_aligned`). Required `evidence_type` on every `rules[]` entry. Optional `confidence` field. | Unconditional labels (e.g. `triggers_game_win`) over-assert determinism for conditional code paths. Evidence grounding improves trust in generated output. | Generation produces more accurate causal claims. Evaluation can filter/weight rules by evidence type and confidence. |
