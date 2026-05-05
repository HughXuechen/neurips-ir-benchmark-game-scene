# IR v0 Schema

Intermediate Representation for scene-level Unity generation.

## Rationale

The IR v0 sits between the GDD constraint layer and the Unity API executor
(see README "Representation decision"). Its fields map directly to Unity's
structural primitives: GameObjects, Components, scene YAML blocks, and Prefabs
(see README "Unity Structural Foundations"). The schema is intentionally
minimal—just enough to describe a playable scene without hand-editing `.unity`
YAML.

## Top-Level Structure

An IR v0 document is a single JSON object with these fields:

| Field       | Type     | MVP Status   | Purpose                                                     |
|-------------|----------|--------------|-------------------------------------------------------------|
| `scene`     | string   | required     | Scene name / identifier.                                    |
| `objects`   | array    | required     | GameObjects that compose the scene.                         |
| `scripts`   | array    | required     | Component scripts attached to objects.                      |
| `params`    | object   | **deferred** | Configurable fields per script instance. Omitted in MVP.    |
| `links`     | array    | required     | Structural relations between objects and components.        |
| `rules`     | array    | required     | Completion / win / loss conditions for the scene.           |

## Field Definitions

### scene

A short identifier for the scene (e.g. `"Ownership_CoinCollect"`).

### objects

Each entry represents one GameObject.

- `id` (string) — unique identifier within the scene.
- `name` (string) — display / prefab name.
- `type` (string) — category hint, e.g. `"player"`, `"pickup"`, `"manager"`.

### scripts

Each entry represents one Component script attached to an object.

- `id` (string) — unique identifier for this script instance.
- `object_id` (string) — references an `objects[].id`.
- `class_name` (string) — C# class name (e.g. `"CoinSpawner"`).

### params *(deferred — not extracted in MVP)*

Maps script instance IDs to their serialized field values. Planned subfields:

- `script_id` (string) — references a `scripts[].id`.
- `fields` (object) — key/value pairs of serialized fields.

Params extraction requires resolving scene -> prefab -> script GUID -> `.cs`
mapping. This is deferred to a post-MVP step to support reproducibility and
structured evaluation.

### links

Each entry captures a structural relation.

- `source` (string) — `objects[].id` or `scripts[].id`.
- `target` (string) — `objects[].id` or `scripts[].id`.
- `relation` (string) — e.g. `"attached_to"`, `"references"`, `"child_of"`.

### rules

Each entry defines a completion or gameplay condition.

- `id` (string) — unique identifier.
- `type` (string) — e.g. `"count"`, `"destination"`, `"spatial"`.
- `description` (string) — human-readable condition text.
- `pattern` (string) — goal pattern this rule derives from (e.g. `"Ownership"`).

## MVP Scope

The MVP pipeline produces IR documents with **objects, scripts, links, and
rules** only. The `params` field is either absent or an empty object (`{}`).
This keeps the initial pipeline fast and unblocked by GUID resolution.

## Minimal Example (MVP)

```json
{
  "scene": "Ownership_CoinCollect",
  "objects": [
    { "id": "obj_player",  "name": "Player",      "type": "player"  },
    { "id": "obj_spawner", "name": "CoinSpawner",  "type": "manager" },
    { "id": "obj_coin",    "name": "Coin",          "type": "pickup"  }
  ],
  "scripts": [
    { "id": "scr_move",    "object_id": "obj_player",  "class_name": "PlayerMovement" },
    { "id": "scr_spawn",   "object_id": "obj_spawner", "class_name": "CoinSpawner"    },
    { "id": "scr_collect", "object_id": "obj_player",  "class_name": "CoinCollector"  }
  ],
  "params": {},
  "links": [
    { "source": "scr_spawn",   "target": "obj_coin",   "relation": "references" },
    { "source": "scr_collect", "target": "obj_coin",   "relation": "references" }
  ],
  "rules": [
    { "id": "rule_win", "type": "count", "description": "Collect 10 coins", "pattern": "Ownership" }
  ]
}
```
