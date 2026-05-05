#!/usr/bin/env python3
"""
Batch generator for runtime IR v0 files for all 26 goal scenes.
Reads parsed JSON + links JSON, resolves GUIDs, applies pattern-specific templates.
"""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent.parent
SCENE_DIR = ROOT / "data" / "raw" / "unity" / "Assets" / "Scenes" / "Goal"
PARSED_DIR = ROOT / "data" / "processed" / "scene_analysis"
OUT_DIR = ROOT / "data" / "processed" / "ir_runtime"

# ── GUID maps ──────────────────────────────────────────────────────────────
PREFAB_GUID = {
    "33b6183c2b6ab0941985288b09041aea": "Game Manager",
    "ba09bb8af5c36d544b90ed2b98dc3ae9": "Goal Manager",
    "98f5227c0b4e8534fbfcb08636b0c279": "Spawn Manager",
    "0d3da064e60a5df47bac0c5fe89a107f": "Delivery Manager",
    "e494bbd1896731841b7a6a51d8f27b2d": "Player",
    "f2a130eacc756ff438ec277276e42302": "PlayerShooter",
    "c1cee042b77714048b43bc8a67996c5f": "Boundary",
    "057536c2a19bd9e4b8cdb1cb044a64f1": "OwnershipObject",
    "6e30f83f3bf38fe4bbe1dbaa84ed28e0": "ChangeColorObject",
    "24202ce96cc263b449455cc0ac86f526": "EliminateObject",
    "53e6a6d6a4489be4993f95f9a9b45a97": "CaptureObject",
    "3434e11a72cb5a244af2d811f652e1cb": "Enemy",
    "7e006f4e45fd4e84f89911355a316c9e": "ChasingEnemy",
    "f26d605542fa0244b832f0488e94bd4b": "ChaseEnemy",
    "d54218958477c80489c777bb9d16cc68": "RandomMoveEnemy Variant",
    "9e67de04b990f5e44bc05eef50b1fa34": "RandomMoveObject",
    "980c44ad901ca4048bafc2049eda0a71": "ConnectObject",
    "4f94b83c2c3a3d143854ee85520cab84": "ConnectObject_Line",
    "b3497ab2c4f5a8949aff7a1fa23651c1": "ExploreObject",
    "c11a234af487f8e4d8c7b79a7000486f": "InformationObject",
    "9d01320081a83704a92ab0db332d9fbd": "NewExploreObjects",
    "891bd6e44a1c303419975768bcaef21f": "KingObject",
    "d2e50e81605447644b0096fa00a763ff": "SpeedUpObject",
    "2d50500034f3db04cbc06240f5faa02f": "LightArea",
    "d5ee2cf78f5ab0d408c08145f8bda5a4": "AIShootingTowardsPlayer",
    "03d788fb13b150742808f7297cf92c0c": "NearestShootAI",
    "3d44b0d458195434ca873bb1ec36b482": "RandomShootAI",
    "561c7873683cb734291464bfb41bcc03": "BulletEnemy Variant",
    "4ed6a397843a155408409d31f516f5d9": "Bullet_EliminateEnemy",
    "3d91ab0345048f84aa1e6c1435c9e023": "Bullet_HitWin",
    "b011a09c1dc9434408f9008d372b45f5": "Bullet_HitWin 1",
    "dcda5e799d446894284a2d8d950043a9": "OvercomBullet",
    "b37e4ff7dfd8cb045bef5067ec2cfea7": "SpawnLightArea",
}

SCRIPT_GUID = {
    "674bb744a46a12046adbc45f1e611424": "GameManager",
    "74fe5acd14b013f4c81b62c11c9822af": "GoalManager",
    "da1bda79679ecaa4fa3caec614254343": "SpawnManager",
    "3939c7439bb8cb343aedbacebfd56bef": "DeliveryManager",
    "a05b66757652d994e81c0ddc167a7318": "PlayerController",
    "04d207b7b2670c14ebd4da7b408f9972": "PlayerControllerShooter",
    "bf0ca91b4b8dd0b428be6650bf748531": "ChangeColor",
    "4d602fadfc357a24986911cea03d47f5": "ChangePlayerColor",
    "231bc3859f8a72a469d96c6d0740f0d2": "Chase",
    "c0cbe861a76bac749bd6163bb41f6322": "Eliminate",
    "296bcc6810f9e894b905c850766cf720": "Delivery",
    "cf400ea7114ea2e42b9d59f4d2b9e588": "ReachDestination",
    "50cd3bd52aa099348ab311c20eea45ff": "Drag",
    "f21e4097615c5484e87a910c8913b3a0": "DragAlignment",
    "599161a890acb2040b9ec9ce3e8a0a37": "DragConfiguration",
    "57ef9c698c03bf94bb72d06bb69e4201": "ConfigRule",
    "50ccd9e3ce2315846aef6faac8bdc1b7": "AlignObjects",
    "6f3df1c60b33c664bb428becf10b301e": "Conceal",
    "856a73f3791c6c34da0db54d050e776e": "EnemyDetect",
    "70415b4b01771714893bc08fbbe61d2f": "Enemy",
    "4f1daf6b11912084fa7a34cdb8f44799": "RandomMove",
    "b605e199bc72f6c42a42541d62257a83": "RandomTargets",
    "d3309512dfd8b3d4e9014bf242a51fae": "MultiplayerDestination",
    "6d9c688e5e4b9bb468739c778b46ce9c": "WaypointFollower",
    "9ec34d8fbd49b5b4794fe0b3c70f4f8b": "ConnectionObject",
    "449e234034164de44bb8d7b4ade0c413": "ConnectionObjectLine",
    "6f65132e6926fb54aad9c0fc1b179230": "DrawLine",
    "d1cb5b474e51d4945b670737a2d43f5a": "GainInformation",
    "ce1a3a7c0ac71ed4fb6f8bd085f3f1e8": "ExploreObject",
    "e44df7b7a3283494b9da44611618f9be": "FirstVisible",
    "e8f4fa0820e27654e958d203740f5ec7": "DistroyOverTime",
    "c8f1c51167996d34bb8d9685153beee0": "ColorManager",
    "14a93e426ad26ed4dab3a5236d0395d9": "AutoChangeColor",
    "a80bb5fbe0b3be145b41d994449db03c": "EnclosureManager",
    "2f95f81795489f34f837b38749d1d94f": "EnclosureObject",
    "b51652a309fa8c34698d191bc57910d9": "LastOneCount",
    "98cde662aae30ff4689162d6b02ddaab": "KingCount",
    "9538c2f92026d51448dfe07a40a0fb49": "KingManager",
    "325e324e76c46ce49858ab3ac41f406d": "Bullet",
    "7b9bc23578d37cf48b417e10eefe289b": "OvercomeBullet",
    "19c117db0f1fda84ba64e49d079e41e3": "PlayerAI",
    "90355c2e5ea316142996b7ec2df97523": "RandomShoot",
    "7d5f97e203edc314f921caf551864ab9": "NearestShoot",
    "efecf816eebec93469883e6ba8f08546": "Counter",
    "2450bc004af264945bd4a7b2ff975f4c": "Menu",
    "d81efbfca4e9e364694d81e7ded5a6ce": "Timer",
    "957ca77d0fe370641bd6ff0608671fc0": "AgentMove",
    "149574eb6b6e80c408b87eba0b1dd40f": "SpeedUp",
    "e4fee0007ac337a45a61d4205ce868a1": "Repel",
    "c8bbad93bcab13a4a9b7aab96d69908e": "Hover",
    "e21778b0617ade8488eeb7ebfc5732e9": "LevelButton",
    "148387606d0ccd84fa326ca211f274ba": "NavMeshSurface2d",
    "b37e4ff7dfd8cb045bef5067ec2cfea7": "SpawnLightArea",
    "e066cb615c2815848b7fadb2e4415877": "Singleton",
}

# Scripts embedded in each prefab (prefab name → list of class names)
PREFAB_SCRIPTS = {
    "Game Manager": ["GameManager"],
    "Goal Manager": ["GoalManager"],
    "Spawn Manager": ["SpawnManager"],
    "Delivery Manager": ["DeliveryManager"],
    "Player": ["PlayerController"],
    "PlayerShooter": ["PlayerControllerShooter"],
    "Enemy": ["WaypointFollower", "Enemy", "EnemyDetect"],
    "CaptureObject": ["ChangeColor", "RandomMove", "Eliminate"],
    "OwnershipObject": ["ChangeColor"],
    "ChangeColorObject": ["ChangePlayerColor"],
    "EliminateObject": ["ChangeColor", "Eliminate"],
    "ExploreObject": ["Eliminate", "ChangeColor"],
    "InformationObject": ["ExploreObject"],
    "NewExploreObjects": ["ChangeColor", "Eliminate", "DistroyOverTime", "FirstVisible"],
    "ConnectObject": ["ConnectionObject"],
    "ConnectObject_Line": ["ConnectionObjectLine"],
    "KingObject": [],
    "ChasingEnemy": ["Chase"],
    "ChaseEnemy": ["Chase"],
    "RandomMoveEnemy Variant": ["RandomMove"],
    "RandomMoveObject": ["RandomMove"],
    "AIShootingTowardsPlayer": ["PlayerAI", "RandomMove"],
    "NearestShootAI": ["RandomMove", "NearestShoot"],
    "RandomShootAI": ["RandomMove", "RandomShoot"],
    "SpeedUpObject": [],
}

# UI/infrastructure scripts to skip in the IR
SKIP_SCRIPTS = {
    "Menu", "Counter", "LevelButton", "Singleton", "NavMeshSurface2d",
    "SpawnLightArea", "Hover", "Timer", "AgentMove", "DrawLine",
    "PlayerController",  # embedded in Player prefab, handled separately
    "DOTweenAnimation", "DOTweenAnimationInspector",
}

# Unity built-in script GUIDs to skip
SKIP_GUIDS = {
    "dc42784cf147c0c48a680349fa168899",  # CanvasScaler
    "0cd44c1031e13a943bb63640046fad76",  # GraphicRaycaster
    "5f7201a12d95ffc409449d95f23cf332",  # Text
    "fe87c0e1cc204ed48ad3b37840f39efc",  # Image
    "4e29b1a8efbd4b44bb3f3716e73f07ff",  # Button
    "76c392e42b5098c458856cdf6ecaaaa1",  # VerticalLayoutGroup
    "4f231c4fb786f3946a6b90b886c48677",  # ContentSizeFitter
    "1e3fdca004f2d45fe8abbed571a8abd5",  # BoxCollider2D (Unity built-in)
    "31a19414c41e5ae4aae2af33fee712f6",  # SpriteRenderer variant
}

# Fields to skip in runtime_params
SKIP_FIELDS = {"serializedVersion", "m_ObjectHideFlags", "m_CorrespondingSourceObject",
               "m_PrefabInstance", "m_PrefabAsset", "m_Enabled", "m_Script", "m_GameObject",
               "m_EditorHideFlags", "m_EditorClassIdentifier"}


def read_parsed(scene_name):
    with open(PARSED_DIR / f"{scene_name}_parsed.json") as f:
        return json.load(f)


def read_links(scene_name):
    with open(PARSED_DIR / f"{scene_name}_links.json") as f:
        return json.load(f)


def extract_scene_data(scene_name):
    """Extract objects, scripts, and MB field data from parsed scene."""
    parsed = read_parsed(scene_name)
    links = read_links(scene_name)
    bbt = parsed["blocksByType"]

    # GameObjects
    gameobjects = {}
    for go in bbt.get("GameObject", []):
        fid = str(go["fileID"])
        name = go["data"].get("GameObject", {}).get("m_Name", fid)
        gameobjects[fid] = name

    # PrefabInstances
    prefab_instances = {}
    for pi in bbt.get("PrefabInstance", []):
        fid = str(pi["fileID"])
        d = pi["data"].get("PrefabInstance", {})
        guid = d.get("m_SourcePrefab", {}).get("guid", "")
        pname = PREFAB_GUID.get(guid, f"Unknown_{guid[:8]}")
        prefab_instances[fid] = {"name": pname, "guid": guid}

    # MonoBehaviours (scene-local)
    monobehaviours = []
    for mb in bbt.get("MonoBehaviour", []):
        d = mb["data"].get("MonoBehaviour", {})
        script_guid = d.get("m_Script", {}).get("guid", "")
        go_ref = str(d.get("m_GameObject", {}).get("fileID", ""))
        class_name = SCRIPT_GUID.get(script_guid, "")
        # Extract serialized fields
        fields = {}
        for k, v in d.items():
            if k.startswith("m_") or k in SKIP_FIELDS:
                continue
            fields[k] = v
        monobehaviours.append({
            "fileID": str(mb["fileID"]),
            "script_guid": script_guid,
            "go_ref": go_ref,
            "class_name": class_name,
            "fields": fields,
        })

    return {
        "gameobjects": gameobjects,
        "prefab_instances": prefab_instances,
        "monobehaviours": monobehaviours,
        "go_to_mb": links["links"].get("gameObject_to_monobehaviours", {}),
        "go_names": links["links"].get("gameObject_name", {}),
    }


def make_script_id(class_name, object_id):
    return f"script_{class_name.lower()}_{object_id}"


def build_ir(scene_name, pattern_name, scene_data, config):
    """Build the complete runtime IR for a scene."""
    pi = scene_data["prefab_instances"]
    gos = scene_data["gameobjects"]
    mbs = scene_data["monobehaviours"]

    # ── Objects ────────────────────────────────────────────────────────────
    objects = []

    # Add GameObjects that are game-relevant (have custom MBs or in config)
    go_ids_with_scripts = set()
    for mb in mbs:
        if mb["script_guid"] not in SKIP_GUIDS and mb["class_name"] not in SKIP_SCRIPTS:
            go_ids_with_scripts.add(mb["go_ref"])

    # Include explicitly listed objects from config
    extra_go_ids = set(config.get("extra_gameobject_ids", []))

    for fid, name in sorted(gos.items(), key=lambda x: x[1]):
        if fid in go_ids_with_scripts or fid in extra_go_ids or name in config.get("include_go_names", set()):
            objects.append({"id": fid, "name": name, "type": "GameObject"})

    # Always include Main Camera if present
    for fid, name in gos.items():
        if name == "Main Camera" and not any(o["id"] == fid for o in objects):
            objects.insert(0, {"id": fid, "name": name, "type": "GameObject"})

    # Add PrefabInstances
    for fid, info in sorted(pi.items(), key=lambda x: x[1]["name"]):
        if info["name"] == "Boundary":
            objects.append({"id": fid, "name": info["name"], "type": "PrefabInstance"})
        elif info["name"] not in config.get("skip_prefabs", set()):
            objects.append({"id": fid, "name": info["name"], "type": "PrefabInstance"})

    # Add PrefabAssets from config
    for pa in config.get("prefab_assets", []):
        objects.append(pa)

    # ── Scripts ────────────────────────────────────────────────────────────
    scripts = []

    # Scene-local MonoBehaviours
    for mb in mbs:
        if mb["script_guid"] in SKIP_GUIDS or mb["class_name"] in SKIP_SCRIPTS:
            continue
        if not mb["class_name"]:
            continue
        obj_id = mb["go_ref"]
        sid = make_script_id(mb["class_name"], obj_id)
        scripts.append({
            "id": sid,
            "object_id": obj_id,
            "class_name": mb["class_name"],
        })

    # Prefab-embedded scripts from config
    for ps in config.get("prefab_scripts", []):
        scripts.append(ps)

    # ── Auto-resolve missing objects ───────────────────────────────────────
    # If any script references an object_id not in objects, add it as a
    # PrefabInstance child GameObject with an inferred name.
    existing_obj_ids = {o["id"] for o in objects}
    for s in scripts:
        oid = s["object_id"]
        if oid and oid not in existing_obj_ids and not oid.startswith("prefab_"):
            # Try to find name from links data
            go_name = scene_data.get("go_names", {}).get(oid, "")
            if not go_name:
                # Infer name from class (it's a PI child)
                go_name = f"{s['class_name']}Object"
            objects.append({"id": oid, "name": go_name, "type": "GameObject"})
            existing_obj_ids.add(oid)

    # ── Links ──────────────────────────────────────────────────────────────
    ir_links = []

    # has_prefab_instance links
    for fid in pi:
        if pi[fid]["name"] not in config.get("skip_prefabs", set()):
            ir_links.append({"source": "scene", "target": fid, "relation": "has_prefab_instance"})

    # has_component links for scene-local scripts
    for s in scripts:
        obj_id = s["object_id"]
        # Check if object exists in our objects list
        if any(o["id"] == obj_id for o in objects):
            ir_links.append({"source": obj_id, "target": s["id"], "relation": "has_component"})

    # Semantic links from config (dedup against structural)
    existing_links = {(l["source"], l["target"], l["relation"]) for l in ir_links}
    for sl in config.get("semantic_links", []):
        key = (sl["source"], sl["target"], sl["relation"])
        if key not in existing_links:
            ir_links.append(sl)
            existing_links.add(key)

    # ── Runtime params ─────────────────────────────────────────────────────
    runtime_params = {}

    # From scene-local MBs
    for mb in mbs:
        if mb["script_guid"] in SKIP_GUIDS or mb["class_name"] in SKIP_SCRIPTS:
            continue
        if not mb["class_name"] or not mb["fields"]:
            continue
        obj_id = mb["go_ref"]
        sid = make_script_id(mb["class_name"], obj_id)
        # Filter to meaningful fields
        filtered = {}
        for k, v in mb["fields"].items():
            if isinstance(v, dict) and "fileID" in v:
                continue  # Skip object references
            if k.startswith("_"):
                filtered[k] = v
            else:
                filtered[k] = v
        if filtered:
            runtime_params[sid] = filtered

    # Prefab-embedded runtime params from config
    for k, v in config.get("prefab_runtime_params", {}).items():
        runtime_params[k] = v

    # ── Rules ──────────────────────────────────────────────────────────────
    rules = config.get("rules", [])

    return {
        "scene": scene_name,
        "objects": objects,
        "scripts": scripts,
        "params": {},
        "runtime_params": runtime_params,
        "links": ir_links,
        "rules": rules,
    }


# ── Pattern configs ────────────────────────────────────────────────────────

def find_pi_by_prefab(scene_data, prefab_name):
    """Find PI fileID by prefab name."""
    for fid, info in scene_data["prefab_instances"].items():
        if info["name"] == prefab_name:
            return fid
    return None


def find_all_pi_by_prefab(scene_data, prefab_name):
    """Find all PI fileIDs by prefab name."""
    return [fid for fid, info in scene_data["prefab_instances"].items()
            if info["name"] == prefab_name]


def find_mbs_by_class(scene_data, class_name):
    """Find all MonoBehaviours of a given class."""
    return [mb for mb in scene_data["monobehaviours"] if mb["class_name"] == class_name]


def find_gos_by_name_pattern(scene_data, pattern):
    """Find GameObjects whose name matches a pattern."""
    return [(fid, name) for fid, name in scene_data["gameobjects"].items()
            if re.match(pattern, name)]


def build_common_prefab_scripts(scene_data):
    """Build prefab script entries for common prefabs (GameManager, GoalManager, SpawnManager)."""
    scripts = []
    gm_id = find_pi_by_prefab(scene_data, "Game Manager")
    if gm_id:
        scripts.append({"id": "script_gamemanager", "object_id": gm_id, "class_name": "GameManager"})
    goal_id = find_pi_by_prefab(scene_data, "Goal Manager")
    if goal_id:
        scripts.append({"id": "script_goalmanager", "object_id": goal_id, "class_name": "GoalManager"})
    spawn_id = find_pi_by_prefab(scene_data, "Spawn Manager")
    if spawn_id:
        scripts.append({"id": "script_spawnmanager", "object_id": spawn_id, "class_name": "SpawnManager"})
    dm_id = find_pi_by_prefab(scene_data, "Delivery Manager")
    if dm_id:
        scripts.append({"id": "script_deliverymanager", "object_id": dm_id, "class_name": "DeliveryManager"})
    return scripts


def build_common_prefab_links(scene_data):
    """Build has_component links for common prefab scripts."""
    links = []
    gm_id = find_pi_by_prefab(scene_data, "Game Manager")
    if gm_id:
        links.append({"source": gm_id, "target": "script_gamemanager", "relation": "has_component"})
    goal_id = find_pi_by_prefab(scene_data, "Goal Manager")
    if goal_id:
        links.append({"source": goal_id, "target": "script_goalmanager", "relation": "has_component"})
    spawn_id = find_pi_by_prefab(scene_data, "Spawn Manager")
    if spawn_id:
        links.append({"source": spawn_id, "target": "script_spawnmanager", "relation": "has_component"})
    dm_id = find_pi_by_prefab(scene_data, "Delivery Manager")
    if dm_id:
        links.append({"source": dm_id, "target": "script_deliverymanager", "relation": "has_component"})
    return links


def build_common_prefab_runtime_params(scene_data):
    """Build runtime_params for common prefab scripts."""
    params = {}
    if find_pi_by_prefab(scene_data, "Spawn Manager"):
        params["script_spawnmanager"] = {
            "spawnStart": True, "spawnCount": 8,
            "spawnRepeat": False, "spawnRangeX": 8.5, "spawnRangeY": 4.5,
        }
    if find_pi_by_prefab(scene_data, "Goal Manager"):
        params["script_goalmanager"] = {
            "goalCount": 8, "currentCount": 0, "setGoal": True,
        }
    if find_pi_by_prefab(scene_data, "Delivery Manager"):
        params["script_deliverymanager"] = {
            "maxDelivery": 1, "totalDeliveriesCompleted": 0,
            "currentDelivery": 0, "totalDeliveries": 0,
        }
    return params


# ── Scene-specific config builders ─────────────────────────────────────────

def config_1_ownership(sd):
    return {
        "prefab_scripts": [],
        "prefab_assets": [],
        "prefab_runtime_params": {},
        "semantic_links": [],
        "rules": [
            {"id": "rule_spawn_ownership_objects", "type": "spawn", "description": "SpawnManager spawns ChangeColorObject prefabs that represent ownable objects in the scene.", "pattern": "Ownership", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_player_claims_ownership", "type": "trigger_count", "description": "When Player enters a ChangeColorObject trigger, the object changes color to indicate ownership and GoalManager.currentCount increases.", "pattern": "Ownership", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_when_all_owned", "type": "win_condition", "description": "When GoalManager.currentCount reaches goalCount, GameManager.GameWin() is called.", "pattern": "Ownership", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_11_delivery(sd):
    return {
        "prefab_scripts": [],
        "prefab_assets": [],
        "prefab_runtime_params": {},
        "semantic_links": [],
        "rules": [
            {"id": "rule_spawn_delivery_objects", "type": "spawn", "description": "SpawnManager spawns pickup objects (Circle) for the player to collect and deliver.", "pattern": "Delivery", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_player_picks_up_item", "type": "trigger_count", "description": "When Player enters a pickup object trigger, the item is attached to the player for delivery.", "pattern": "Delivery", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_player_delivers_to_target", "type": "trigger_count", "description": "When Player carrying an item enters the delivery zone (Square), DeliveryManager records the delivery and increments the count.", "pattern": "Delivery", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_when_deliveries_complete", "type": "win_condition", "description": "When DeliveryManager.totalDeliveriesCompleted reaches maxDelivery, GameManager.GameWin() is called.", "pattern": "Delivery", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_14_alignment_new(sd):
    return {
        "prefab_scripts": [],
        "prefab_assets": [],
        "prefab_runtime_params": {},
        "semantic_links": [],
        "rules": [
            {"id": "rule_spawn_alignment_objects", "type": "spawn", "description": "SpawnManager spawns draggable Circle objects and their target positions in the scene.", "pattern": "Alignment", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_player_drags_objects", "type": "interaction", "description": "Player can click and drag Circle objects to new positions using the DragAlignment script.", "pattern": "Alignment", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_when_all_aligned", "type": "win_condition", "description": "When all draggable objects overlap their target zones, AlignObjects confirms alignment and GameManager.GameWin() is called.", "pattern": "Alignment", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_2_collection(sd):
    spawn_id = find_pi_by_prefab(sd, "Spawn Manager")
    goal_id = find_pi_by_prefab(sd, "Goal Manager")
    spawn_prefab_guid = "6e30f83f3bf38fe4bbe1dbaa84ed28e0"  # ChangeColorObject
    return {
        "prefab_scripts": build_common_prefab_scripts(sd) + [
            {"id": f"script_{spawn_prefab_guid}", "object_id": f"prefab_{spawn_prefab_guid}", "class_name": "ChangePlayerColor"},
        ],
        "prefab_assets": [
            {"id": f"prefab_{spawn_prefab_guid}", "name": "ChangeColorObject", "type": "PrefabAsset"},
        ],
        "prefab_runtime_params": {
            **build_common_prefab_runtime_params(sd),
            f"script_{spawn_prefab_guid}": {"finalOne": False},
        },
        "semantic_links": build_common_prefab_links(sd) + [
            {"source": f"script_{spawn_prefab_guid}", "target": f"prefab_{spawn_prefab_guid}", "relation": "has_component"},
            {"source": f"script_spawnmanager", "target": f"prefab_{spawn_prefab_guid}", "relation": "spawns_prefab", "evidence_type": "direct_code"},
            {"source": f"script_{spawn_prefab_guid}", "target": "script_goalmanager", "relation": "increments_current_count_on_trigger", "evidence_type": "direct_code"},
            {"source": "script_goalmanager", "target": "script_gamemanager", "relation": "can_trigger_game_win_if_count_met", "evidence_type": "direct_code"},
        ],
        "rules": [
            {"id": "rule_spawn_collectibles", "type": "spawn", "description": "SpawnManager spawns ChangeColorObject prefab on Start when spawnStart is true.", "pattern": "Collection", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_collect_changes_color_and_counts", "type": "trigger_count", "description": "When Player enters a ChangeColorObject trigger, the object changes to a collected color and GoalManager.currentCount increases by 1.", "pattern": "Collection", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_when_count_reaches_goal", "type": "win_condition", "description": "If GoalManager.setGoal is true and currentCount equals goalCount, GameManager.GameWin() is called.", "pattern": "Collection", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_3_eliminate(sd):
    spawn_id = find_pi_by_prefab(sd, "Spawn Manager")
    spawn_prefab_guid = "24202ce96cc263b449455cc0ac86f526"  # EliminateObject
    return {
        "prefab_scripts": build_common_prefab_scripts(sd) + [
            {"id": f"script_changecolor_{spawn_prefab_guid}", "object_id": f"prefab_{spawn_prefab_guid}", "class_name": "ChangeColor"},
            {"id": f"script_eliminate_{spawn_prefab_guid}", "object_id": f"prefab_{spawn_prefab_guid}", "class_name": "Eliminate"},
        ],
        "prefab_assets": [
            {"id": f"prefab_{spawn_prefab_guid}", "name": "EliminateObject", "type": "PrefabAsset"},
        ],
        "prefab_runtime_params": {
            **build_common_prefab_runtime_params(sd),
            f"script_eliminate_{spawn_prefab_guid}": {"collidePlayer": True, "collideGameobject": False},
        },
        "semantic_links": build_common_prefab_links(sd) + [
            {"source": f"prefab_{spawn_prefab_guid}", "target": f"script_changecolor_{spawn_prefab_guid}", "relation": "has_component"},
            {"source": f"prefab_{spawn_prefab_guid}", "target": f"script_eliminate_{spawn_prefab_guid}", "relation": "has_component"},
            {"source": "script_spawnmanager", "target": f"prefab_{spawn_prefab_guid}", "relation": "spawns_prefab", "evidence_type": "direct_code"},
            {"source": f"script_eliminate_{spawn_prefab_guid}", "target": "script_goalmanager", "relation": "increments_current_count_on_trigger", "evidence_type": "inferred"},
            {"source": "script_goalmanager", "target": "script_gamemanager", "relation": "can_trigger_game_win_if_count_met", "evidence_type": "direct_code"},
        ],
        "rules": [
            {"id": "rule_spawn_enemies", "type": "spawn", "description": "SpawnManager spawns EliminateObject prefab on Start.", "pattern": "Eliminate", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_eliminate_on_collision", "type": "trigger_count", "description": "When Player collides with an EliminateObject, the object is destroyed and GoalManager.currentCount increases.", "pattern": "Eliminate", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_when_all_eliminated", "type": "win_condition", "description": "If GoalManager.setGoal is true and currentCount equals goalCount, GameManager.GameWin() is called.", "pattern": "Eliminate", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_4_capture(sd):
    spawn_prefab_guid = "53e6a6d6a4489be4993f95f9a9b45a97"  # CaptureObject
    return {
        "prefab_scripts": build_common_prefab_scripts(sd) + [
            {"id": f"script_changecolor_{spawn_prefab_guid}", "object_id": f"prefab_{spawn_prefab_guid}", "class_name": "ChangeColor"},
            {"id": f"script_eliminate_{spawn_prefab_guid}", "object_id": f"prefab_{spawn_prefab_guid}", "class_name": "Eliminate"},
            {"id": f"script_randommove_{spawn_prefab_guid}", "object_id": f"prefab_{spawn_prefab_guid}", "class_name": "RandomMove"},
        ],
        "prefab_assets": [
            {"id": f"prefab_{spawn_prefab_guid}", "name": "CaptureObject", "type": "PrefabAsset"},
        ],
        "prefab_runtime_params": {
            **build_common_prefab_runtime_params(sd),
            f"script_randommove_{spawn_prefab_guid}": {"moveSpeed": 3},
            f"script_eliminate_{spawn_prefab_guid}": {"collidePlayer": True, "collideGameobject": False},
        },
        "semantic_links": build_common_prefab_links(sd) + [
            {"source": f"prefab_{spawn_prefab_guid}", "target": f"script_changecolor_{spawn_prefab_guid}", "relation": "has_component"},
            {"source": f"prefab_{spawn_prefab_guid}", "target": f"script_eliminate_{spawn_prefab_guid}", "relation": "has_component"},
            {"source": f"prefab_{spawn_prefab_guid}", "target": f"script_randommove_{spawn_prefab_guid}", "relation": "has_component"},
            {"source": "script_spawnmanager", "target": f"prefab_{spawn_prefab_guid}", "relation": "spawns_prefab", "evidence_type": "direct_code"},
            {"source": f"script_eliminate_{spawn_prefab_guid}", "target": "script_goalmanager", "relation": "increments_current_count_on_trigger", "evidence_type": "inferred"},
            {"source": "script_goalmanager", "target": "script_gamemanager", "relation": "can_trigger_game_win_if_count_met", "evidence_type": "direct_code"},
        ],
        "rules": [
            {"id": "rule_spawn_capture_objects", "type": "spawn", "description": "SpawnManager spawns CaptureObject prefab. Each CaptureObject moves randomly via RandomMove.", "pattern": "Capture", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_capture_on_collision", "type": "trigger_count", "description": "When Player collides with a CaptureObject, the object is captured (destroyed) and GoalManager.currentCount increases.", "pattern": "Capture", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_when_all_captured", "type": "win_condition", "description": "If GoalManager.setGoal is true and currentCount equals goalCount, GameManager.GameWin() is called.", "pattern": "Capture", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_5_overcome(sd):
    player_id = find_pi_by_prefab(sd, "PlayerShooter")
    ai_id = find_pi_by_prefab(sd, "AIShootingTowardsPlayer")
    return {
        "prefab_scripts": build_common_prefab_scripts(sd) + [
            {"id": "script_playercontrollershooter", "object_id": player_id or "", "class_name": "PlayerControllerShooter"},
            {"id": "script_playerai", "object_id": ai_id or "", "class_name": "PlayerAI"},
        ],
        "prefab_runtime_params": build_common_prefab_runtime_params(sd),
        "semantic_links": build_common_prefab_links(sd) + [
            {"source": player_id or "", "target": "script_playercontrollershooter", "relation": "has_component"},
            {"source": ai_id or "", "target": "script_playerai", "relation": "has_component"},
            {"source": "script_playercontrollershooter", "target": "script_gamemanager", "relation": "can_trigger_game_win_on_enemy_hit", "evidence_type": "direct_code"},
            {"source": "script_playerai", "target": "script_gamemanager", "relation": "can_trigger_game_lose_on_player_hit", "evidence_type": "direct_code"},
        ],
        "rules": [
            {"id": "rule_player_shoots_bullets", "type": "shoot", "description": "Player fires bullets using PlayerControllerShooter. Bullets travel toward mouse direction.", "pattern": "Overcome", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_ai_shoots_at_player", "type": "shoot", "description": "AI fires bullets toward Player position on a timed interval.", "pattern": "Overcome", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_hit_enemy", "type": "win_condition", "description": "When a PlayerBullet hits the AI enemy, GameManager.GameWin() is called.", "pattern": "Overcome", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_lose_hit_by_enemy", "type": "lose_condition", "description": "When an EnemyBullet hits the Player, GameManager.GameLose() is called.", "pattern": "Overcome", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_6_evade(sd):
    chase_mbs = find_mbs_by_class(sd, "Chase")
    circles = find_gos_by_name_pattern(sd, r"Circle.*")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in chase_mbs:
        sid = make_script_id("Chase", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_lose_on_touch", "evidence_type": "direct_code"})

    return {
        "include_go_names": {name for _, name in circles},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_enemies_chase_player", "type": "chase", "description": "Each Circle has a Chase script that moves toward the Player at a set speed.", "pattern": "Evade", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_lose_on_enemy_touch", "type": "lose_condition", "description": "When a chasing Circle touches the Player (touchEvent=true), GameManager.GameLose() is called.", "pattern": "Evade", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_survive_to_win", "type": "win_condition", "description": "Player must avoid all chasing enemies. Win condition is time-based or triggered externally.", "pattern": "Evade", "evidence_type": "inferred", "confidence": 0.7},
        ],
    }


def config_7_stealth(sd):
    enemy_pis = find_all_pi_by_prefab(sd, "Enemy")
    dest_gos = find_gos_by_name_pattern(sd, r"Destination")
    sq_gos = find_gos_by_name_pattern(sd, r"Square.*")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)

    for eid in enemy_pis:
        sem_links.append({"source": eid, "target": f"script_waypointfollower_{eid}", "relation": "has_component"})
        sem_links.append({"source": eid, "target": f"script_enemydetect_{eid}", "relation": "has_component"})
        sem_links.append({"source": f"script_enemydetect_{eid}", "target": "script_gamemanager", "relation": "can_trigger_game_lose_on_detect", "evidence_type": "direct_code"})
        prefab_scripts.append({"id": f"script_waypointfollower_{eid}", "object_id": eid, "class_name": "WaypointFollower"})
        prefab_scripts.append({"id": f"script_enemydetect_{eid}", "object_id": eid, "class_name": "EnemyDetect"})

    rd_mbs = find_mbs_by_class(sd, "ReachDestination")
    for mb in rd_mbs:
        sid = make_script_id("ReachDestination", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_on_destination", "evidence_type": "direct_code"})

    return {
        "include_go_names": {n for _, n in dest_gos} | {n for _, n in sq_gos},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": build_common_prefab_runtime_params(sd),
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_enemies_patrol", "type": "patrol", "description": "Enemy prefab instances patrol along waypoints using WaypointFollower.", "pattern": "Stealth", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_detect_loses", "type": "lose_condition", "description": "When an Enemy's EnemyDetect trigger contacts the Player, GameManager.GameLose() is called.", "pattern": "Stealth", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_reach_destination_wins", "type": "win_condition", "description": "When Player reaches the Destination object via ReachDestination trigger, GameManager.GameWin() is called.", "pattern": "Stealth", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_8_herd_attract(sd):
    circles = find_gos_by_name_pattern(sd, r"Circle.*")
    squares = find_gos_by_name_pattern(sd, r"Square.*")
    chase_mbs = find_mbs_by_class(sd, "Chase")
    rd_mbs = find_mbs_by_class(sd, "ReachDestination")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in rd_mbs:
        sid = make_script_id("ReachDestination", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_deliverymanager", "relation": "increments_total_deliveries_on_trigger", "evidence_type": "direct_code"})

    for mb in chase_mbs:
        sid = make_script_id("Chase", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_deliverymanager", "relation": "follows_player_when_attracted", "evidence_type": "inferred"})

    sem_links.append({"source": "script_deliverymanager", "target": "script_gamemanager", "relation": "can_trigger_game_win_if_all_delivered", "evidence_type": "direct_code"})

    # Set delivery manager count from circle count
    circle_count = len(circles)
    rt_params["script_deliverymanager"] = {
        "maxDelivery": 1, "totalDeliveriesCompleted": circle_count,
        "currentDelivery": 0, "totalDeliveries": 0,
    }

    return {
        "include_go_names": {n for _, n in circles} | {n for _, n in squares},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_attract_circle", "type": "trigger_follow", "description": "When Player enters a Circle trigger, the Circle follows the Player (Chase with chasePlayer=true).", "pattern": "Herd_Attract", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_deliver_to_square", "type": "trigger_count", "description": "When a following Circle reaches a Square destination (ReachDestination), DeliveryManager.totalDeliveries increments and the Circle is destroyed.", "pattern": "Herd_Attract", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_all_delivered", "type": "win_condition", "description": "When DeliveryManager.totalDeliveries equals totalDeliveriesCompleted, GameManager.GameWin() is called.", "pattern": "Herd_Attract", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_9_conceal(sd):
    enemy_pis = find_all_pi_by_prefab(sd, "Enemy")
    dest_gos = find_gos_by_name_pattern(sd, r"Destination")
    sq_gos = find_gos_by_name_pattern(sd, r"Square.*")
    conceal_mbs = find_mbs_by_class(sd, "Conceal")
    rd_mbs = find_mbs_by_class(sd, "ReachDestination")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)

    for eid in enemy_pis:
        prefab_scripts.append({"id": f"script_waypointfollower_{eid}", "object_id": eid, "class_name": "WaypointFollower"})
        prefab_scripts.append({"id": f"script_enemydetect_{eid}", "object_id": eid, "class_name": "EnemyDetect"})
        sem_links.append({"source": eid, "target": f"script_waypointfollower_{eid}", "relation": "has_component"})
        sem_links.append({"source": eid, "target": f"script_enemydetect_{eid}", "relation": "has_component"})
        sem_links.append({"source": f"script_enemydetect_{eid}", "target": "script_gamemanager", "relation": "can_trigger_game_lose_on_detect", "evidence_type": "direct_code"})

    for mb in conceal_mbs:
        sid = make_script_id("Conceal", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "toggles_player_visibility", "evidence_type": "direct_code"})

    for mb in rd_mbs:
        sid = make_script_id("ReachDestination", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_on_destination", "evidence_type": "direct_code"})

    return {
        "include_go_names": {n for _, n in dest_gos} | {n for _, n in sq_gos},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": build_common_prefab_runtime_params(sd),
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_conceal_toggle", "type": "conceal", "description": "Player presses Space to toggle concealment when in a ConcealArea. Concealment changes alpha to 0.5 and disables physics.", "pattern": "Conceal", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_enemies_patrol", "type": "patrol", "description": "Enemy prefab instances patrol along waypoints. EnemyDetect triggers GameLose on player contact.", "pattern": "Conceal", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_reach_destination_wins", "type": "win_condition", "description": "When Player reaches the Destination via ReachDestination, GameManager.GameWin() is called.", "pattern": "Conceal", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_10_rescue(sd):
    dest_gos = find_gos_by_name_pattern(sd, r"Destination")
    sq_gos = find_gos_by_name_pattern(sd, r"Square.*")
    rescue_gos = find_gos_by_name_pattern(sd, r"RescueObject")
    rd_mbs = find_mbs_by_class(sd, "ReachDestination")
    delivery_mbs = find_mbs_by_class(sd, "Delivery")
    enemy_pis = find_all_pi_by_prefab(sd, "Enemy")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for eid in enemy_pis:
        prefab_scripts.append({"id": f"script_waypointfollower_{eid}", "object_id": eid, "class_name": "WaypointFollower"})
        prefab_scripts.append({"id": f"script_enemydetect_{eid}", "object_id": eid, "class_name": "EnemyDetect"})
        sem_links.append({"source": eid, "target": f"script_waypointfollower_{eid}", "relation": "has_component"})
        sem_links.append({"source": eid, "target": f"script_enemydetect_{eid}", "relation": "has_component"})
        sem_links.append({"source": f"script_enemydetect_{eid}", "target": "script_gamemanager", "relation": "can_trigger_game_lose_on_detect", "evidence_type": "direct_code"})

    for mb in delivery_mbs:
        sid = make_script_id("Delivery", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_deliverymanager", "relation": "increments_current_delivery_on_trigger", "evidence_type": "direct_code"})

    for mb in rd_mbs:
        sid = make_script_id("ReachDestination", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_deliverymanager", "relation": "increments_total_deliveries_on_trigger", "evidence_type": "direct_code"})

    sem_links.append({"source": "script_deliverymanager", "target": "script_gamemanager", "relation": "can_trigger_game_win_if_all_delivered", "evidence_type": "direct_code"})

    rescue_count = len(rescue_gos) + 1  # +1 for the one in scene
    rt_params["script_deliverymanager"] = {
        "maxDelivery": 1, "totalDeliveriesCompleted": rescue_count,
        "currentDelivery": 0, "totalDeliveries": 0,
    }

    return {
        "include_go_names": {n for _, n in dest_gos} | {n for _, n in sq_gos} | {n for _, n in rescue_gos},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_pickup_rescue_object", "type": "trigger_follow", "description": "When Player enters a RescueObject trigger, the object follows Player and DeliveryManager.currentDelivery increments.", "pattern": "Rescue", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_deliver_to_destination", "type": "trigger_count", "description": "When a following RescueObject reaches the Destination, DeliveryManager.totalDeliveries increments and the object is destroyed.", "pattern": "Rescue", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_enemies_patrol", "type": "patrol", "description": "Enemy prefab instances patrol along waypoints. Contact triggers GameLose.", "pattern": "Rescue", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_all_rescued", "type": "win_condition", "description": "When DeliveryManager.totalDeliveries equals totalDeliveriesCompleted, GameManager.GameWin() is called.", "pattern": "Rescue", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_12_guard(sd):
    circles = find_gos_by_name_pattern(sd, r"Circle.*")
    guard_gos = find_gos_by_name_pattern(sd, r"GuardArea")
    chase_mbs = find_mbs_by_class(sd, "Chase")
    elim_mbs = find_mbs_by_class(sd, "Eliminate")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)

    for mb in elim_mbs:
        sid = make_script_id("Eliminate", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "destroys_on_player_collision", "evidence_type": "direct_code"})

    for mb in chase_mbs:
        sid = make_script_id("Chase", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "chases_toward_guard_area", "evidence_type": "inferred"})

    return {
        "include_go_names": {n for _, n in circles} | {n for _, n in guard_gos},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": build_common_prefab_runtime_params(sd),
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_enemies_approach_guard_area", "type": "chase", "description": "Circle enemies chase toward the GuardArea. Each has Chase and Eliminate scripts.", "pattern": "Guard", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_eliminate_enemy_on_collision", "type": "trigger_count", "description": "When Player collides with a Circle enemy, the Eliminate script destroys the enemy.", "pattern": "Guard", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_all_eliminated", "type": "win_condition", "description": "Player wins by eliminating all approaching enemies before they reach the GuardArea.", "pattern": "Guard", "evidence_type": "inferred", "confidence": 0.8},
        ],
    }


def config_13_race(sd):
    circles = find_gos_by_name_pattern(sd, r"Circle.*")
    squares = find_gos_by_name_pattern(sd, r"Square.*")
    targets_go = find_gos_by_name_pattern(sd, r"Targets")
    mp_mbs = find_mbs_by_class(sd, "MultiplayerDestination")
    rt_mbs = find_mbs_by_class(sd, "RandomTargets")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in rt_mbs:
        sid = make_script_id("RandomTargets", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_if_count_met", "evidence_type": "direct_code"})

    for mb in mp_mbs:
        sid = make_script_id("MultiplayerDestination", mb["go_ref"])
        for rmb in rt_mbs:
            rt_sid = make_script_id("RandomTargets", rmb["go_ref"])
            sem_links.append({"source": sid, "target": rt_sid, "relation": "increments_player_count_on_trigger", "evidence_type": "direct_code"})

    return {
        "include_go_names": {n for _, n in circles} | {n for _, n in squares} | {n for _, n in targets_go},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_race_to_targets", "type": "race", "description": "Player and AI compete to reach target Squares. Circles serve as waypoint markers with MultiplayerDestination.", "pattern": "Race", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_target_changes_on_reach", "type": "trigger_count", "description": "When Player or AI reaches a target, RandomTargets.ChangeTarget() selects a new random target and increments the scorer's count.", "pattern": "Race", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_reach_wincount", "type": "win_condition", "description": "When playerCount reaches winCount, GameManager.GameWin() is called. If playerAICount reaches winCount first, GameLose() is called.", "pattern": "Race", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_15_configuration(sd):
    circles = find_gos_by_name_pattern(sd, r"Circle.*")
    pos_gos = find_gos_by_name_pattern(sd, r"Pos.*")
    dc_mbs = find_mbs_by_class(sd, "DragConfiguration")
    cr_mbs = find_mbs_by_class(sd, "ConfigRule")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in cr_mbs:
        sid = make_script_id("ConfigRule", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_if_configured", "evidence_type": "direct_code"})

    for mb in dc_mbs:
        sid = make_script_id("DragConfiguration", mb["go_ref"])
        for cmb in cr_mbs:
            cr_sid = make_script_id("ConfigRule", cmb["go_ref"])
            sem_links.append({"source": sid, "target": cr_sid, "relation": "increments_current_count_on_snap", "evidence_type": "direct_code"})

    return {
        "include_go_names": {n for _, n in circles} | {n for _, n in pos_gos} | {"AlignObjects"},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_drag_to_position", "type": "drag_configuration", "description": "Each Circle has a DragConfiguration script. User drags circles to Pos target positions.", "pattern": "Configuration", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_snap_on_drop", "type": "snap", "description": "On mouse release, if Circle is within 0.5 units of a target position, it snaps and ConfigRule.currentCount increments.", "pattern": "Configuration", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_all_configured", "type": "win_condition", "description": "When ConfigRule.currentCount equals targetCount, GameManager.GameWin() is called.", "pattern": "Configuration", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_16_traverse(sd):
    circles = find_gos_by_name_pattern(sd, r"Circle.*")
    squares = find_gos_by_name_pattern(sd, r"Square.*")
    targets_go = find_gos_by_name_pattern(sd, r"Targets")
    mp_mbs = find_mbs_by_class(sd, "MultiplayerDestination")
    rt_mbs = find_mbs_by_class(sd, "RandomTargets")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in rt_mbs:
        sid = make_script_id("RandomTargets", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_if_count_met", "evidence_type": "direct_code"})

    for mb in mp_mbs:
        sid = make_script_id("MultiplayerDestination", mb["go_ref"])
        for rmb in rt_mbs:
            rt_sid = make_script_id("RandomTargets", rmb["go_ref"])
            sem_links.append({"source": sid, "target": rt_sid, "relation": "increments_player_count_on_trigger", "evidence_type": "direct_code"})

    return {
        "include_go_names": {n for _, n in circles} | {n for _, n in squares} | {n for _, n in targets_go},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_traverse_waypoints", "type": "traverse", "description": "Player navigates through Square waypoints while AI also traverses. Circles mark waypoint positions with MultiplayerDestination.", "pattern": "Traverse", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_target_reached", "type": "trigger_count", "description": "When Player or AI reaches a waypoint, RandomTargets updates the active target and increments the scorer's count.", "pattern": "Traverse", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_traverse_all", "type": "win_condition", "description": "When playerCount reaches winCount, GameManager.GameWin() is called.", "pattern": "Traverse", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_17_survive(sd):
    loc_mbs = find_mbs_by_class(sd, "LastOneCount")
    chase_mbs = find_mbs_by_class(sd, "Chase")
    rm_mbs = find_mbs_by_class(sd, "RandomMove")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in loc_mbs:
        sid = make_script_id("LastOneCount", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_when_count_zero", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_enemies_chase", "type": "chase", "description": "Enemy objects chase the Player using Chase scripts while RandomMove provides auxiliary movement.", "pattern": "Survive", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_enemies_destroy_over_time", "type": "elimination", "description": "LastOneCount tracks a list of enemy objects. Enemies are destroyed over time, decrementing the count.", "pattern": "Survive", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_survive_all", "type": "win_condition", "description": "When LastOneCount.countNum reaches 0 (all enemies gone), GameManager.GameWin() is called.", "pattern": "Survive", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_lose_on_touch", "type": "lose_condition", "description": "If an enemy touches the Player (Chase.touchEvent), GameManager.GameLose() is called.", "pattern": "Survive", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_18_connection_line(sd):
    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    # Look for ConnectObject_Line and ConnectObject PIs
    cl_pis = find_all_pi_by_prefab(sd, "ConnectObject_Line")
    co_pis = find_all_pi_by_prefab(sd, "ConnectObject")

    for pid in cl_pis:
        prefab_scripts.append({"id": f"script_connectionobjectline_{pid}", "object_id": pid, "class_name": "ConnectionObjectLine"})
        sem_links.append({"source": pid, "target": f"script_connectionobjectline_{pid}", "relation": "has_component"})
        sem_links.append({"source": f"script_connectionobjectline_{pid}", "target": "script_gamemanager", "relation": "can_trigger_game_win_on_line_complete", "evidence_type": "direct_code"})

    for pid in co_pis:
        prefab_scripts.append({"id": f"script_connectionobject_{pid}", "object_id": pid, "class_name": "ConnectionObject"})
        sem_links.append({"source": pid, "target": f"script_connectionobject_{pid}", "relation": "has_component"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_draw_line", "type": "connection", "description": "Player touches ConnectObject nodes to draw a line between them using ConnectionObjectLine.", "pattern": "Connection_Line", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_line_complete", "type": "win_condition", "description": "When the line connects from start to end through all intermediate nodes, GameManager.GameWin() is called via coroutine.", "pattern": "Connection_Line", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_19_exploration(sd):
    gi_mbs = find_mbs_by_class(sd, "GainInformation")
    eo_mbs = find_mbs_by_class(sd, "ExploreObject")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    # Look for ExploreObject and InformationObject PIs
    eo_pis = find_all_pi_by_prefab(sd, "ExploreObject")
    io_pis = find_all_pi_by_prefab(sd, "InformationObject")

    for pid in io_pis:
        prefab_scripts.append({"id": f"script_exploreobject_{pid}", "object_id": pid, "class_name": "ExploreObject"})
        sem_links.append({"source": pid, "target": f"script_exploreobject_{pid}", "relation": "has_component"})

    for mb in gi_mbs:
        sid = make_script_id("GainInformation", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_when_all_explored", "evidence_type": "direct_code"})
        for pid in io_pis:
            sem_links.append({"source": f"script_exploreobject_{pid}", "target": sid, "relation": "removes_from_explore_list_on_trigger", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_progressive_discovery", "type": "exploration", "description": "GainInformation starts with one visible ExploreObject. Touching it reveals a random next hidden object.", "pattern": "Exploration", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_all_explored", "type": "win_condition", "description": "When all ExploreObjects have been discovered (list empty), GameManager.GameWin() is called.", "pattern": "Exploration", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_20_reconnaissance(sd):
    gi_mbs = find_mbs_by_class(sd, "GainInformation")
    enemy_pis = find_all_pi_by_prefab(sd, "Enemy")
    io_pis = find_all_pi_by_prefab(sd, "InformationObject")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for pid in io_pis:
        prefab_scripts.append({"id": f"script_exploreobject_{pid}", "object_id": pid, "class_name": "ExploreObject"})
        sem_links.append({"source": pid, "target": f"script_exploreobject_{pid}", "relation": "has_component"})

    for eid in enemy_pis:
        prefab_scripts.append({"id": f"script_waypointfollower_{eid}", "object_id": eid, "class_name": "WaypointFollower"})
        prefab_scripts.append({"id": f"script_enemydetect_{eid}", "object_id": eid, "class_name": "EnemyDetect"})
        sem_links.append({"source": eid, "target": f"script_waypointfollower_{eid}", "relation": "has_component"})
        sem_links.append({"source": eid, "target": f"script_enemydetect_{eid}", "relation": "has_component"})
        sem_links.append({"source": f"script_enemydetect_{eid}", "target": "script_gamemanager", "relation": "can_trigger_game_lose_on_detect", "evidence_type": "direct_code"})

    for mb in gi_mbs:
        sid = make_script_id("GainInformation", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_when_all_explored", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_progressive_discovery", "type": "exploration", "description": "GainInformation reveals ExploreObjects one at a time. Player touches each to discover the next.", "pattern": "Reconnaissance", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_enemies_patrol", "type": "patrol", "description": "Enemy instances patrol with WaypointFollower. EnemyDetect triggers GameLose on player contact.", "pattern": "Reconnaissance", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_all_explored", "type": "win_condition", "description": "When all ExploreObjects are discovered, GameManager.GameWin() is called.", "pattern": "Reconnaissance", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_21_contact(sd):
    rm_mbs = find_mbs_by_class(sd, "RandomMove")
    chase_mbs = find_mbs_by_class(sd, "Chase")
    cpc_mbs = find_mbs_by_class(sd, "ChangePlayerColor")
    cm_mbs = find_mbs_by_class(sd, "ColorManager")
    ac_mbs = find_mbs_by_class(sd, "AutoChangeColor")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    # ChangeColorObject PIs
    cc_pis = find_all_pi_by_prefab(sd, "ChangeColorObject")
    for pid in cc_pis:
        prefab_scripts.append({"id": f"script_changeplayercolor_{pid}", "object_id": pid, "class_name": "ChangePlayerColor"})
        sem_links.append({"source": pid, "target": f"script_changeplayercolor_{pid}", "relation": "has_component"})
        sem_links.append({"source": f"script_changeplayercolor_{pid}", "target": "script_gamemanager", "relation": "can_trigger_game_win_if_correct_color", "evidence_type": "direct_code"})

    for mb in cm_mbs:
        sid = make_script_id("ColorManager", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "manages_target_color", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_spawn_colored_objects", "type": "spawn", "description": "SpawnManager spawns ChangeColorObject instances. One in ten has the winning finalColor.", "pattern": "Contact", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_contact_changes_color", "type": "trigger_color", "description": "When Player touches a ChangeColorObject, ChangePlayerColor checks if its color matches ColorManager.finalColor.", "pattern": "Contact", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_correct_color", "type": "win_condition", "description": "If the contacted object has finalOne=true (matching finalColor), GameManager.GameWin() is called.", "pattern": "Contact", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_22_enclosure(sd):
    rm_mbs = find_mbs_by_class(sd, "RandomMove")
    em_mbs = find_mbs_by_class(sd, "EnclosureManager")
    eo_mbs = find_mbs_by_class(sd, "EnclosureObject")
    circles = find_gos_by_name_pattern(sd, r"Circle.*")
    squares = find_gos_by_name_pattern(sd, r"Square.*")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in em_mbs:
        sid = make_script_id("EnclosureManager", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_on_enclosure_complete", "evidence_type": "direct_code"})

    for mb in eo_mbs:
        sid = make_script_id("EnclosureObject", mb["go_ref"])
        for emb in em_mbs:
            em_sid = make_script_id("EnclosureManager", emb["go_ref"])
            sem_links.append({"source": sid, "target": em_sid, "relation": "adds_polygon_point_on_trigger", "evidence_type": "direct_code"})

    return {
        "include_go_names": {n for _, n in circles} | {n for _, n in squares},
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_touch_to_draw_polygon", "type": "enclosure", "description": "Player touches EnclosureObject nodes to draw a polygon. Each touch adds a vertex and draws a line segment.", "pattern": "Enclosure", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_enclosed_objects_counted", "type": "trigger_count", "description": "When polygon is complete, EnclosureManager checks which objects are inside and colors them.", "pattern": "Enclosure", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_enclosure_complete", "type": "win_condition", "description": "When totalPoints are connected forming a closed polygon, GameManager.GameWin() is called.", "pattern": "Enclosure", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_23_gaincompetence(sd):
    rt_mbs = find_mbs_by_class(sd, "RandomTargets")
    mp_mbs = find_mbs_by_class(sd, "MultiplayerDestination")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for mb in rt_mbs:
        sid = make_script_id("RandomTargets", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_if_count_met", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_compete_for_targets", "type": "competition", "description": "Player and AI compete to reach target positions. MultiplayerDestination tracks who reaches each target first.", "pattern": "GainCompetence", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_outperform_ai", "type": "win_condition", "description": "When playerCount reaches winCount before playerAICount, GameManager.GameWin() is called.", "pattern": "GainCompetence", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_24_gaininformation(sd):
    gi_mbs = find_mbs_by_class(sd, "GainInformation")
    neo_pis = find_all_pi_by_prefab(sd, "NewExploreObjects")
    io_pis = find_all_pi_by_prefab(sd, "InformationObject")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for pid in io_pis:
        prefab_scripts.append({"id": f"script_exploreobject_{pid}", "object_id": pid, "class_name": "ExploreObject"})
        sem_links.append({"source": pid, "target": f"script_exploreobject_{pid}", "relation": "has_component"})

    for pid in neo_pis:
        prefab_scripts.append({"id": f"script_firstvisible_{pid}", "object_id": pid, "class_name": "FirstVisible"})
        prefab_scripts.append({"id": f"script_distroyovertime_{pid}", "object_id": pid, "class_name": "DistroyOverTime"})
        sem_links.append({"source": pid, "target": f"script_firstvisible_{pid}", "relation": "has_component"})
        sem_links.append({"source": pid, "target": f"script_distroyovertime_{pid}", "relation": "has_component"})

    for mb in gi_mbs:
        sid = make_script_id("GainInformation", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_when_all_explored", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_progressive_discovery", "type": "exploration", "description": "GainInformation manages a list of hidden ExploreObjects. One is revealed at a time via FirstVisible.", "pattern": "GainInformation", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_timed_destruction", "type": "timer", "description": "NewExploreObjects self-destruct after a random 1-5 second delay via DistroyOverTime.", "pattern": "GainInformation", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_all_explored", "type": "win_condition", "description": "When all ExploreObjects are discovered (list empty), GameManager.GameWin() is called.", "pattern": "GainInformation", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_25_lastmanstanding(sd):
    loc_mbs = find_mbs_by_class(sd, "LastOneCount")
    rd_mbs = find_mbs_by_class(sd, "ReachDestination")
    chase_mbs = find_mbs_by_class(sd, "Chase")
    enemy_pis = find_all_pi_by_prefab(sd, "Enemy")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for eid in enemy_pis:
        prefab_scripts.append({"id": f"script_waypointfollower_{eid}", "object_id": eid, "class_name": "WaypointFollower"})
        prefab_scripts.append({"id": f"script_enemydetect_{eid}", "object_id": eid, "class_name": "EnemyDetect"})
        sem_links.append({"source": eid, "target": f"script_waypointfollower_{eid}", "relation": "has_component"})
        sem_links.append({"source": eid, "target": f"script_enemydetect_{eid}", "relation": "has_component"})
        sem_links.append({"source": f"script_enemydetect_{eid}", "target": "script_gamemanager", "relation": "can_trigger_game_lose_on_detect", "evidence_type": "direct_code"})

    for mb in loc_mbs:
        sid = make_script_id("LastOneCount", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_when_count_zero", "evidence_type": "direct_code"})

    for mb in rd_mbs:
        sid = make_script_id("ReachDestination", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "can_trigger_game_win_on_destination", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_enemies_chase", "type": "chase", "description": "Enemy instances chase the Player. WaypointFollower provides patrol paths, EnemyDetect triggers lose.", "pattern": "LastManStanding_Escaping", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_enemies_eliminated_over_time", "type": "elimination", "description": "LastOneCount tracks enemies. As enemies are destroyed, the count decrements.", "pattern": "LastManStanding_Escaping", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_reach_destination_wins", "type": "win_condition", "description": "When Player reaches a destination via ReachDestination, or all enemies are eliminated (count=0), GameManager.GameWin() is called.", "pattern": "LastManStanding_Escaping", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


def config_26_kingofthehill(sd):
    kc_mbs = find_mbs_by_class(sd, "KingCount")
    km_mbs = find_mbs_by_class(sd, "KingManager") if find_mbs_by_class(sd, "KingManager") else []
    rm_mbs = find_mbs_by_class(sd, "RandomMove")
    chase_mbs = find_mbs_by_class(sd, "Chase")
    king_pis = find_all_pi_by_prefab(sd, "KingObject")

    prefab_scripts = build_common_prefab_scripts(sd)
    sem_links = build_common_prefab_links(sd)
    rt_params = build_common_prefab_runtime_params(sd)

    for pid in king_pis:
        prefab_scripts.append({"id": f"script_kingobject_{pid}", "object_id": pid, "class_name": "KingObject"})
        sem_links.append({"source": pid, "target": f"script_kingobject_{pid}", "relation": "has_component"})

    for mb in kc_mbs:
        sid = make_script_id("KingCount", mb["go_ref"])
        sem_links.append({"source": sid, "target": "script_gamemanager", "relation": "updates_king_status_on_collect", "evidence_type": "direct_code"})

    return {
        "prefab_scripts": prefab_scripts,
        "prefab_runtime_params": rt_params,
        "semantic_links": sem_links,
        "rules": [
            {"id": "rule_collect_king_objects", "type": "trigger_count", "description": "Player and AI collect KingObjects. KingCount increments per entity on trigger collision.", "pattern": "KingoftheHill", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_king_status_updates", "type": "king_check", "description": "KingManager tracks which entity has the highest kingCountNum. The leader is marked as king with a visual indicator.", "pattern": "KingoftheHill", "evidence_type": "direct_code", "confidence": 1.0},
            {"id": "rule_win_be_king", "type": "win_condition", "description": "When all KingObjects are collected, if Player has the highest count, GameManager.GameWin() is called.", "pattern": "KingoftheHill", "evidence_type": "direct_code", "confidence": 1.0},
        ],
    }


# ── Scene dispatch ─────────────────────────────────────────────────────────

SCENE_CONFIG = {
    "1_Ownership": ("Ownership", config_1_ownership),
    "2_Collection": ("Collection", config_2_collection),
    "3_Eliminate": ("Eliminate", config_3_eliminate),
    "4_Capture": ("Capture", config_4_capture),
    "5_Overcome": ("Overcome", config_5_overcome),
    "6_Evade": ("Evade", config_6_evade),
    "7_Stealth": ("Stealth", config_7_stealth),
    "8_Herd_Attract": ("Herd_Attract", config_8_herd_attract),
    "9_Conceal": ("Conceal", config_9_conceal),
    "10_Rescue": ("Rescue", config_10_rescue),
    "11_Delivery": ("Delivery", config_11_delivery),
    "12_Guard": ("Guard", config_12_guard),
    "13_Race": ("Race", config_13_race),
    "14_Alignment_new": ("Alignment", config_14_alignment_new),
    "15_Configuration": ("Configuration", config_15_configuration),
    "16_Traverse": ("Traverse", config_16_traverse),
    "17_Survive": ("Survive", config_17_survive),
    "18_Connection_Line": ("Connection_Line", config_18_connection_line),
    "19_Exploration": ("Exploration", config_19_exploration),
    "20_Reconnaissance": ("Reconnaissance", config_20_reconnaissance),
    "21_Contact": ("Contact", config_21_contact),
    "22_Enclosure": ("Enclosure", config_22_enclosure),
    "23_GainCompetence": ("GainCompetence", config_23_gaincompetence),
    "24_GainInformation": ("GainInformation", config_24_gaininformation),
    "25_LastManStanding_Escaping": ("LastManStanding_Escaping", config_25_lastmanstanding),
    "26_KingoftheHill": ("KingoftheHill", config_26_kingofthehill),
}

ALREADY_DONE = set()  # reprocess all from goal_flatten


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Runtime IR Batch Generator")
    print("=" * 60)

    ok, fail = 0, 0
    for scene_name, (pattern_name, config_fn) in SCENE_CONFIG.items():
        if scene_name in ALREADY_DONE:
            print(f"  SKIP  {scene_name} (already exists)")
            continue

        try:
            sd = extract_scene_data(scene_name)
            config = config_fn(sd)
            ir = build_ir(scene_name, pattern_name, sd, config)

            out_path = OUT_DIR / f"{scene_name}_ir_v0_runtime.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(ir, f, indent=2, ensure_ascii=False)

            n_obj = len(ir["objects"])
            n_scr = len(ir["scripts"])
            n_lnk = len(ir["links"])
            n_rul = len(ir["rules"])
            print(f"  OK    {scene_name} -- obj={n_obj} scr={n_scr} lnk={n_lnk} rul={n_rul}")
            ok += 1
        except Exception as e:
            import traceback
            print(f"  FAIL  {scene_name} -- {e}")
            traceback.print_exc()
            fail += 1

    print(f"\nDone: {ok} generated, {fail} failed")


if __name__ == "__main__":
    main()
