# IR Changelog

All schema changes are logged here. The current frozen version is listed first.

---

## v0.2-runtime-evidence (current, frozen)

### Added
- `runtime_params` top-level field (keyed by `scripts[].id`).
- `PrefabInstance` and `PrefabAsset` as valid `objects[].type` values.
- `evidence_type` field on `rules[]` entries (`direct_code` | `scene_override` | `inferred`).
- Optional `confidence` (0.0--1.0) on rules.
- `evidence_type` optional on `links[]` for causal/behavioral edges.

### Changed
- Relation labels use conservative conditional phrasing for non-deterministic
  behavior (e.g. `can_trigger_*` instead of `triggers_*`).

### Constraints
- Scripts are per-instance; `scripts[].object_id` MUST resolve to a real
  `objects[].id`.
- No implicit aggregate placeholders (e.g. `circle_all`).
- Every `rules[]` entry MUST include `evidence_type`.
- `params` remains `{}` (deferred to post-MVP).

### Freeze Policy
- No schema shape changes without an explicit version bump (e.g. `v0.3`).
- Any future change MUST be logged in this file before merging.

### Methodology Note (2025-02 review)
- IR schema shape remains unchanged after reviewing schema-constrained
  decoding literature (see `literature/schema-constrained.pdf`).
- Schema-constrained decoding is tracked as a future generation-stage
  enhancement; it affects how IR is produced, not what fields IR contains.
- This note records an architectural decision, not a schema revision.

---

## Unreleased (v0.3 draft ideas)

- TODO: `params` extraction via GUID resolution (scene -> prefab -> script -> `.cs`).
- TODO: Typed sub-schemas for `runtime_params` per script class.
- TODO: Evaluate whether `links[].evidence_type` should become required.
- TODO: Consider adding `objects[].components` inline array as alternative to separate `scripts` table.
- TODO: Optional constrained IR generation (decoding/validation), without changing IR field definitions.
