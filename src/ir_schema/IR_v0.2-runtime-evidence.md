# IR v0.2-runtime-evidence

**Status:** Canonical frozen schema
**Version:** IR v0.2-runtime-evidence

## Top-Level Fields

| Field            | Type   | Required | Description                                      |
|------------------|--------|----------|--------------------------------------------------|
| `scene`          | string | yes      | Scene name / identifier.                         |
| `objects`        | array  | yes      | GameObjects and PrefabInstances in the scene.    |
| `scripts`        | array  | yes      | Component scripts attached to objects.           |
| `params`         | object | deferred | Per-script serialized fields. Currently `{}`.    |
| `runtime_params` | object | yes      | Runtime-critical fields keyed by script id.      |
| `links`          | array  | yes      | Structural and causal relations between entities.|
| `rules`          | array  | yes      | Win/progress/gameplay conditions with evidence.  |

## Field Definitions

### scene
Short identifier string (e.g. `"1_Ownership"`).

### objects
Each entry is one GameObject or PrefabInstance.
- `id` (string) -- unique within the scene.
- `name` (string) -- display / prefab name.
- `type` (string) -- `"GameObject"`, `"PrefabInstance"`, or `"PrefabAsset"`.

### scripts
Each entry is one Component script bound to a specific object.
- `id` (string) -- unique script instance id.
- `object_id` (string) -- MUST reference a real `objects[].id`.
- `class_name` (string) -- C# class name.

### params
Maps script ids to serialized field values. **Deferred in MVP** -- always `{}`.

### runtime_params
Maps script ids to runtime-critical field values extracted from code analysis.
Keys are `scripts[].id`; values are flat key/value objects.

### links
Each entry is a directed relation.
- `source` (string) -- `objects[].id`, `scripts[].id`, or `"scene"`.
- `target` (string) -- `objects[].id` or `scripts[].id`.
- `relation` (string) -- e.g. `"has_prefab_instance"`, `"has_component"`, `"spawns_prefab"`.
- `evidence_type` (string, optional on structural links) -- see Evidence Model.

### rules
Each entry defines a gameplay condition.
- `id` (string) -- unique rule id.
- `type` (string) -- e.g. `"spawn"`, `"win_condition"`, `"trigger_count"`.
- `description` (string) -- human-readable condition text.
- `pattern` (string) -- goal pattern this rule derives from.
- `evidence_type` (string, **required**) -- see Evidence Model.
- `confidence` (float, optional) -- 0.0--1.0.

## Hard Constraints (MUST)

1. Scripts are **per-instance** only. Each script entry represents exactly one
   component on one object.
2. Every `scripts[].object_id` MUST resolve to a real `objects[].id`.
   No dangling references.
3. No implicit aggregate placeholders (e.g. `circle_all`). Every referenced
   entity must appear explicitly in `objects`.
4. Every `rules[]` entry MUST include `evidence_type`.

## Relation Naming Guideline

Use **conservative conditional labels** for non-deterministic behavior.
Example: `can_trigger_game_win_if_aligned` instead of `triggers_game_win`.
Unconditional labels are only appropriate when code unconditionally executes
the action with no guarding condition.

## Evidence Model

| `evidence_type`  | Meaning                                           |
|------------------|---------------------------------------------------|
| `direct_code`    | Behavior verified directly in source `.cs` files. |
| `scene_override` | Value set via scene/prefab serialization override. |
| `inferred`       | Behavior inferred from context, not verified.     |

`confidence` (float 0.0--1.0) is optional and indicates certainty of the claim.

## MVP Note

`params` is currently `{}` and deferred. Extraction requires resolving
scene -> prefab -> script GUID -> `.cs` mapping and is planned for post-MVP.

## Scope Boundary (current freeze)

v0.2-runtime-evidence defines the IR representation only. Constrained
decoding and structured output validation are generation-pipeline concerns
and do not belong to the schema definition. No fields have been added,
removed, or redefined in this update. Schema-constrained generation
techniques (e.g. grammar-guided decoding) may be applied at IR production
time without altering the v0.2 field set.

## Scope Decision (Current)

- IR v0.2 is Unity-grounded and remains the active target. All fields,
  relations, and evidence types assume Unity scene/prefab/component
  semantics.
- No engine-agnostic IR layer will be added in the current phase.
  Cross-engine abstraction (Unreal, Godot) is out of scope for v0.2.
- Engine-portable abstraction is deferred to future versions. If pursued,
  it would sit above this Unity-specific IR as a separate translation
  layer.

## Minimal Example

```json
{
  "scene": "1_Ownership",
  "objects": [
    { "id": "1112099645", "name": "Player", "type": "PrefabInstance" },
    { "id": "9011082862537914474", "name": "Spawn Manager", "type": "PrefabInstance" },
    { "id": "prefab_coin", "name": "OwnershipObject", "type": "PrefabAsset" }
  ],
  "scripts": [
    { "id": "scr_spawn", "object_id": "9011082862537914474", "class_name": "SpawnManager" },
    { "id": "scr_color", "object_id": "prefab_coin", "class_name": "ChangeColor" }
  ],
  "params": {},
  "runtime_params": {
    "scr_spawn": { "spawnStart": true, "spawnCount": 8 }
  },
  "links": [
    { "source": "scene", "target": "9011082862537914474", "relation": "has_prefab_instance" },
    { "source": "9011082862537914474", "target": "scr_spawn", "relation": "has_component" },
    { "source": "scr_spawn", "target": "prefab_coin", "relation": "spawns_prefab", "evidence_type": "direct_code" }
  ],
  "rules": [
    {
      "id": "rule_spawn_on_start",
      "type": "spawn",
      "description": "SpawnManager spawns OwnershipObject on Start.",
      "pattern": "Ownership",
      "evidence_type": "direct_code",
      "confidence": 1.0
    }
  ]
}
```
