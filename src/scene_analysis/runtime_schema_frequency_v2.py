#!/usr/bin/env python3
"""Generate runtime_schema_frequency_v2 artifacts from all 26 runtime IR files."""

import json
import glob
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IR_DIR = ROOT / "data" / "processed" / "ir_runtime"
REPORT_DIR = ROOT / "data" / "processed" / "ir_schema_reports"
V1_PATH = REPORT_DIR / "runtime_schema_frequency_v1.json"
OUT_JSON = REPORT_DIR / "runtime_schema_frequency_v2.json"
OUT_MD = REPORT_DIR / "runtime_schema_frequency_v2.md"

CORE_THRESH = 0.80
COMMON_THRESH = 0.40


def classify(ratio):
    if ratio >= CORE_THRESH:
        return "core"
    elif ratio >= COMMON_THRESH:
        return "common"
    return "optional"


def build_entry(count, scenes_present, sample_count, per_sample=None):
    ratio = round(scenes_present / sample_count, 4)
    entry = {
        "total_occurrences": count,
        "scenes_present": scenes_present,
        "coverage_ratio": ratio,
        "classification": classify(ratio),
    }
    if per_sample is not None:
        entry["per_sample_counts"] = per_sample
    return entry


def analyze():
    files = sorted(glob.glob(str(IR_DIR / "*_ir_v0_runtime.json")))
    sample_count = len(files)
    assert sample_count == 26, f"Expected 26 files, found {sample_count}"

    samples = [os.path.basename(f) for f in files]

    # Accumulators
    top_level_count = defaultdict(lambda: {"count": 0, "scenes": set()})
    obj_type_count = defaultdict(lambda: {"count": 0, "scenes": set(), "per_sample": {}})
    script_class_count = defaultdict(lambda: {"count": 0, "scenes": set(), "per_sample": {}})
    link_rel_count = defaultdict(lambda: {"count": 0, "scenes": set(), "per_sample": {}})
    rule_type_count = defaultdict(lambda: {"count": 0, "scenes": set(), "per_sample": {}})
    rule_ev_count = defaultdict(lambda: {"count": 0, "scenes": set(), "per_sample": {}})
    rp_global_count = defaultdict(lambda: {"count": 0, "scenes": set()})
    rp_by_class = defaultdict(lambda: defaultdict(lambda: {"count": 0, "scenes": set()}))

    for fpath in files:
        fname = os.path.basename(fpath)
        scene_key = fname.replace("_ir_v0_runtime.json", "")
        data = json.load(open(fpath))

        # Top-level fields
        for k in data.keys():
            top_level_count[k]["count"] += 1
            top_level_count[k]["scenes"].add(scene_key)

        # Build script id -> class_name map for runtime_params
        script_id_to_class = {}
        for s in data.get("scripts", []):
            sid = s.get("id", "")
            cn = s.get("class_name", "")
            if sid and cn:
                script_id_to_class[sid] = cn

        # objects[].type
        obj_counts_local = defaultdict(int)
        for obj in data.get("objects", []):
            t = obj.get("type", "unknown")
            obj_counts_local[t] += 1
        for t, c in obj_counts_local.items():
            obj_type_count[t]["count"] += c
            obj_type_count[t]["scenes"].add(scene_key)
            obj_type_count[t]["per_sample"][scene_key] = c

        # scripts[].class_name
        sc_local = defaultdict(int)
        for s in data.get("scripts", []):
            cn = s.get("class_name", "unknown")
            sc_local[cn] += 1
        for cn, c in sc_local.items():
            script_class_count[cn]["count"] += c
            script_class_count[cn]["scenes"].add(scene_key)
            script_class_count[cn]["per_sample"][scene_key] = c

        # links[].relation
        lr_local = defaultdict(int)
        for l in data.get("links", []):
            rel = l.get("relation", "unknown")
            lr_local[rel] += 1
        for rel, c in lr_local.items():
            link_rel_count[rel]["count"] += c
            link_rel_count[rel]["scenes"].add(scene_key)
            link_rel_count[rel]["per_sample"][scene_key] = c

        # rules[].type, rules[].evidence_type
        rt_local = defaultdict(int)
        re_local = defaultdict(int)
        for r in data.get("rules", []):
            rt = r.get("type", "unknown")
            rt_local[rt] += 1
            et = r.get("evidence_type", "unknown")
            re_local[et] += 1
        for rt, c in rt_local.items():
            rule_type_count[rt]["count"] += c
            rule_type_count[rt]["scenes"].add(scene_key)
            rule_type_count[rt]["per_sample"][scene_key] = c
        for et, c in re_local.items():
            rule_ev_count[et]["count"] += c
            rule_ev_count[et]["scenes"].add(scene_key)
            rule_ev_count[et]["per_sample"][scene_key] = c

        # runtime_params
        rp = data.get("runtime_params", {})
        for script_id, params in rp.items():
            if not isinstance(params, dict):
                continue
            class_name = script_id_to_class.get(script_id, script_id)
            for key in params.keys():
                rp_global_count[key]["count"] += 1
                rp_global_count[key]["scenes"].add(scene_key)
                rp_by_class[class_name][key]["count"] += 1
                rp_by_class[class_name][key]["scenes"].add(scene_key)

    # Build output dicts
    def make_section(acc, with_per_sample=True):
        result = {}
        for name, info in sorted(acc.items(), key=lambda x: -len(x[1]["scenes"])):
            entry = build_entry(
                info["count"], len(info["scenes"]), sample_count,
                info.get("per_sample") if with_per_sample else None,
            )
            result[name] = entry
        return result

    def make_section_simple(acc):
        result = {}
        for name, info in sorted(acc.items(), key=lambda x: -len(x[1]["scenes"])):
            result[name] = build_entry(info["count"], len(info["scenes"]), sample_count)
        return result

    top_level = make_section_simple(top_level_count)
    object_types = make_section(obj_type_count)
    script_classes = make_section(script_class_count)
    link_relations = make_section(link_rel_count)
    rule_types = make_section(rule_type_count)
    rule_evidence_types = make_section(rule_ev_count)

    rp_global = make_section_simple(rp_global_count)
    rp_by_script = {}
    for cls_name, keys_acc in sorted(rp_by_class.items()):
        rp_by_script[cls_name] = make_section_simple(keys_acc)

    runtime_param_keys = {"global": rp_global, "by_script_class": rp_by_script}

    # Classification summary
    all_sections = {
        "top_level_fields": top_level,
        "object_types": object_types,
        "script_classes": script_classes,
        "link_relations": link_relations,
        "rule_types": rule_types,
        "rule_evidence_types": rule_evidence_types,
        "runtime_param_keys": rp_global,
    }
    classification = {"core": {}, "common": {}, "optional": {}}
    for section_name, section_data in all_sections.items():
        for tier in classification:
            classification[tier][section_name] = [
                k for k, v in section_data.items() if v["classification"] == tier
            ]

    # Delta from v1
    delta = {"promoted": [], "demoted": [], "new_entries": []}
    if V1_PATH.exists():
        v1 = json.load(open(V1_PATH))
        v1_class = v1.get("classification", {})
        # Build v1 tier map: item -> (section, tier)
        v1_tier_map = {}
        for tier in ("core", "common", "optional"):
            tier_data = v1_class.get(tier, {})
            for section, items in tier_data.items():
                if isinstance(items, list):
                    for item in items:
                        v1_tier_map[(section, item)] = tier
        # Compare
        tier_rank = {"core": 2, "common": 1, "optional": 0}
        for section_name, section_data in all_sections.items():
            for item, info in section_data.items():
                v2_tier = info["classification"]
                key = (section_name, item)
                if key in v1_tier_map:
                    v1_tier = v1_tier_map[key]
                    if tier_rank[v2_tier] > tier_rank[v1_tier]:
                        delta["promoted"].append(
                            {"item": item, "section": section_name,
                             "from": v1_tier, "to": v2_tier}
                        )
                    elif tier_rank[v2_tier] < tier_rank[v1_tier]:
                        delta["demoted"].append(
                            {"item": item, "section": section_name,
                             "from": v1_tier, "to": v2_tier}
                        )
                else:
                    delta["new_entries"].append(
                        {"item": item, "section": section_name, "tier": v2_tier}
                    )

    result = {
        "version": "runtime_schema_frequency_v2",
        "sample_count": sample_count,
        "samples": samples,
        "thresholds": {
            "core": f">= {CORE_THRESH:.0%} of samples ({int(CORE_THRESH * sample_count)}/{sample_count})",
            "common": f">= {COMMON_THRESH:.0%} and < {CORE_THRESH:.0%} ({int(COMMON_THRESH * sample_count)}/{sample_count} to {int(CORE_THRESH * sample_count) - 1}/{sample_count})",
            "optional": f"< {COMMON_THRESH:.0%} (< {int(COMMON_THRESH * sample_count)}/{sample_count})",
        },
        "top_level": top_level,
        "object_types": object_types,
        "script_classes": script_classes,
        "link_relations": link_relations,
        "rule_types": rule_types,
        "rule_evidence_types": rule_evidence_types,
        "runtime_param_keys": runtime_param_keys,
        "classification": classification,
        "stability_delta_from_v1": delta,
        "notes": [
            f"Generated from {sample_count} runtime IR files.",
            "Coverage ratio = scenes_present / sample_count.",
            "runtime_param_keys.global aggregates all param keys across all scripts/scenes.",
            "runtime_param_keys.by_script_class groups param keys by the owning script class_name.",
            "Delta computed against runtime_schema_frequency_v1.json (3-sample baseline).",
        ],
    }

    # Write JSON
    with open(OUT_JSON, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # Write Markdown
    write_markdown(result, delta)

    # Validate
    json.loads(json.dumps(result, default=str))
    assert result["sample_count"] == 26

    # Summary
    print(f"\n=== SUMMARY ===")
    print(f"sample_count: {sample_count}")
    core_lr = [k for k, v in link_relations.items() if v["classification"] == "core"]
    print(f"Top 5 core link relations: {core_lr[:5]}")
    core_rt = [k for k, v in rule_types.items() if v["classification"] == "core"]
    core_re = [k for k, v in rule_evidence_types.items() if v["classification"] == "core"]
    combined = core_rt + core_re
    print(f"Top 5 core rule entries (types+evidence): {combined[:5]}")
    print(f"Output: {OUT_JSON}")
    print(f"Output: {OUT_MD}")


def write_markdown(result, delta):
    lines = []
    sc = result["sample_count"]

    lines.append("# Runtime Schema Frequency Analysis v2")
    lines.append("")
    lines.append(f"**Version:** `{result['version']}`  ")
    lines.append(f"**Sample count:** {sc}  ")
    lines.append(f"**Thresholds:** Core ≥ 80% | Common ≥ 40% | Optional < 40%")
    lines.append("")

    def table(section_data, title, top_n=None):
        lines.append(f"## {title}")
        lines.append("")
        items = list(section_data.items())
        if top_n:
            items = items[:top_n]
        lines.append("| Item | Occurrences | Scenes | Coverage | Tier |")
        lines.append("|------|------------|--------|----------|------|")
        for name, info in items:
            lines.append(
                f"| `{name}` | {info['total_occurrences']} | {info['scenes_present']}/{sc} "
                f"| {info['coverage_ratio']:.0%} | {info['classification']} |"
            )
        lines.append("")

    table(result["top_level"], "Top-Level Fields")
    table(result["object_types"], "Object Types")
    table(result["script_classes"], "Script Classes")
    table(result["link_relations"], "Link Relations — Top 10 by Coverage", top_n=10)

    # Full link relations
    lines.append("### All Link Relations")
    lines.append("")
    lines.append("| Relation | Occurrences | Scenes | Coverage | Tier |")
    lines.append("|----------|------------|--------|----------|------|")
    for name, info in result["link_relations"].items():
        lines.append(
            f"| `{name}` | {info['total_occurrences']} | {info['scenes_present']}/{sc} "
            f"| {info['coverage_ratio']:.0%} | {info['classification']} |"
        )
    lines.append("")

    table(result["rule_types"], "Rule Types — Top 10 by Coverage", top_n=10)

    # Full rule types
    lines.append("### All Rule Types")
    lines.append("")
    lines.append("| Type | Occurrences | Scenes | Coverage | Tier |")
    lines.append("|------|------------|--------|----------|------|")
    for name, info in result["rule_types"].items():
        lines.append(
            f"| `{name}` | {info['total_occurrences']} | {info['scenes_present']}/{sc} "
            f"| {info['coverage_ratio']:.0%} | {info['classification']} |"
        )
    lines.append("")

    table(result["rule_evidence_types"], "Rule Evidence Types")

    # Runtime param keys global
    lines.append("## Runtime Param Keys — Global")
    lines.append("")
    rp_global = result["runtime_param_keys"]["global"]
    lines.append("| Key | Occurrences | Scenes | Coverage | Tier |")
    lines.append("|-----|------------|--------|----------|------|")
    for name, info in list(rp_global.items())[:30]:
        lines.append(
            f"| `{name}` | {info['total_occurrences']} | {info['scenes_present']}/{sc} "
            f"| {info['coverage_ratio']:.0%} | {info['classification']} |"
        )
    if len(rp_global) > 30:
        lines.append(f"| ... | *{len(rp_global) - 30} more* | | | |")
    lines.append("")

    # Runtime param keys by script class (top classes)
    lines.append("## Runtime Param Keys — By Script Class (top classes)")
    lines.append("")
    by_class = result["runtime_param_keys"]["by_script_class"]
    for cls_name, keys_data in list(by_class.items())[:15]:
        lines.append(f"### `{cls_name}`")
        lines.append("")
        lines.append("| Key | Occurrences | Scenes | Coverage | Tier |")
        lines.append("|-----|------------|--------|----------|------|")
        for key, info in keys_data.items():
            lines.append(
                f"| `{key}` | {info['total_occurrences']} | {info['scenes_present']}/{sc} "
                f"| {info['coverage_ratio']:.0%} | {info['classification']} |"
            )
        lines.append("")

    # Classification summary
    lines.append("## Classification Summary")
    lines.append("")
    cls = result["classification"]
    for tier in ("core", "common", "optional"):
        lines.append(f"### {tier.title()}")
        lines.append("")
        for section, items in cls[tier].items():
            if items:
                lines.append(f"- **{section}**: {', '.join(f'`{i}`' for i in items)}")
        lines.append("")

    # Delta from v1
    lines.append("## Stability Delta from v1")
    lines.append("")
    if delta["promoted"]:
        lines.append("### Promoted")
        lines.append("")
        lines.append("| Item | Section | From | To |")
        lines.append("|------|---------|------|----|")
        for d in delta["promoted"]:
            lines.append(f"| `{d['item']}` | {d['section']} | {d['from']} | {d['to']} |")
        lines.append("")
    if delta["demoted"]:
        lines.append("### Demoted")
        lines.append("")
        lines.append("| Item | Section | From | To |")
        lines.append("|------|---------|------|----|")
        for d in delta["demoted"]:
            lines.append(f"| `{d['item']}` | {d['section']} | {d['from']} | {d['to']} |")
        lines.append("")
    if delta["new_entries"]:
        lines.append("### New Entries")
        lines.append("")
        lines.append("| Item | Section | Tier |")
        lines.append("|------|---------|------|")
        for d in delta["new_entries"]:
            lines.append(f"| `{d['item']}` | {d['section']} | {d['tier']} |")
        lines.append("")
    if not any(delta.values()):
        lines.append("No changes detected.")
        lines.append("")

    # Caveats
    lines.append("## Caveats")
    lines.append("")
    lines.append("- v1 was based on 3 samples; v2 uses all 26, so tier shifts are expected.")
    lines.append("- `runtime_params` keys are matched via script ID → class_name mapping; "
                  "unresolved IDs appear as raw script IDs.")
    lines.append("- Coverage ratios are scene-level (a key appearing in multiple scripts "
                  "within one scene still counts as 1 scene).")
    lines.append("")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    analyze()
