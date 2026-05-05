"""Generate V2 / V4 IR excerpts for Appendix J.

Shows one complete behavior script entry + complete condition_path + tags (V2),
and one complete scene GO entry (V4 adds). All original fields preserved.
Truncation uses _truncated sentinel key (never "..." string values).

Pattern: 1_Ownership
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
V2_FILE = BASE / "data/ir_v2/1_Ownership_ir_v2_full.json"
V4_FILE = BASE / "data/ir_v4/1_Ownership_ir_v4.json"


def main():
    v2 = json.load(V2_FILE.open())
    v4 = json.load(V4_FILE.open())

    import copy
    beh = copy.deepcopy(v2["behavior"])
    all_cls = list(beh.keys())
    first_cls = all_cls[0]

    # --- Truncation 1: keep only 2 paper-relevant methods ---
    methods = beh[first_cls].get("methods", {})
    if len(methods) > 2:
        keep_keys = [k for k in ["Awake", "GameWin"] if k in methods]
        if len(keep_keys) < 2:
            keep_keys = list(methods.keys())[:2]
        methods_pruned = {k: methods[k] for k in keep_keys}
        methods_pruned["_truncated"] = f"{len(methods) - len(keep_keys)} more methods omitted"
        beh[first_cls]["methods"] = methods_pruned

    # --- Truncation 2: evidence basename only; drop method_body ---
    cp = copy.deepcopy(v2["condition_path"])
    for step in cp.get("win", []):
        if "evidence" in step:
            step["evidence"] = step["evidence"].split("/")[-1]
        step.pop("method_body", None)

    # V2 output
    v2_out = {
        "pattern": v2["pattern"],
        "version": v2["version"],
        "behavior": {
            first_cls: beh[first_cls],
            "_truncated": f"{len(all_cls) - 1} more script entries omitted",
        },
        "condition_path": cp,
        "tags": v2["tags"],
    }

    # --- Truncation 3: strip m_ Unity-internal fields from scene components ---
    import copy as _copy
    scene = _copy.deepcopy(v4["scene"])
    for go_name, go_data in scene.items():
        if go_name.startswith("_"):
            continue
        for comp in go_data.get("components", []):
            if "data" in comp:
                comp["data"] = {k: v for k, v in comp["data"].items()
                                if not k.startswith("m_")}

    # --- Truncation 4: transform — keep only position ---
    for go_name, go_data in scene.items():
        if go_name.startswith("_"):
            continue
        if "transform" in go_data:
            pos = go_data["transform"].get("position")
            go_data["transform"] = {"position": pos} if pos is not None else {}

    scene_keys = list(scene.keys())
    chosen_go = "Goal Manager"
    v4_out = {
        "pattern": v4["pattern"],
        "version": v4["version"],
        "_note": "behavior/condition_path/tags identical to v2; scene{} is the addition",
        "scene": {
            chosen_go: scene[chosen_go],
            "_truncated": f"{len(scene_keys) - 1} more GameObjects omitted",
        },
    }

    print("% --- V2 (behavior-only) IR: 1_Ownership [first script + full condition_path] ---")
    print(json.dumps(v2_out, indent=2))
    print()
    print("% --- V4 (full-scene) adds scene{} block (1 of 11 GOs shown) ---")
    print(json.dumps(v4_out, indent=2))

    # Line count
    lines = (
        json.dumps(v2_out, indent=2).count("\n") +
        json.dumps(v4_out, indent=2).count("\n")
    )
    print(f"\n[INFO] JSON lines: {lines}")


if __name__ == "__main__":
    main()
