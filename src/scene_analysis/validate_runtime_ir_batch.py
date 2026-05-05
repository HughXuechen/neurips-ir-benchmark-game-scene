#!/usr/bin/env python3
"""
Validate all runtime IR v0 files and produce batch validation report.
Checks: valid JSON, no unresolved object IDs, non-empty rules, all rules have evidence_type.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent.parent
IR_DIR = ROOT / "data" / "processed" / "ir_runtime"
REPORT_DIR = ROOT / "data" / "processed" / "ir_schema_reports"

ALL_SCENES = [
    "1_Ownership", "2_Collection", "3_Eliminate", "4_Capture",
    "5_Overcome", "6_Evade", "7_Stealth", "8_Herd_Attract",
    "9_Conceal", "10_Rescue", "11_Delivery", "12_Guard",
    "13_Race", "14_Alignment_new", "15_Configuration", "16_Traverse",
    "17_Survive", "18_Connection_Line", "19_Exploration",
    "20_Reconnaissance", "21_Contact", "22_Enclosure",
    "23_GainCompetence", "24_GainInformation",
    "25_LastManStanding_Escaping", "26_KingoftheHill",
]

REQUIRED_TOP_LEVEL = ["scene", "objects", "scripts", "params", "runtime_params", "links", "rules"]


def validate_scene(scene_name):
    """Validate a single runtime IR file. Returns (result_dict, issues_list)."""
    file_path = IR_DIR / f"{scene_name}_ir_v0_runtime.json"
    result = {
        "scene": scene_name,
        "file": str(file_path.name),
        "exists": False,
        "valid_json": False,
        "objects_count": 0,
        "scripts_count": 0,
        "links_count": 0,
        "rules_count": 0,
        "unresolved_object_ids": 0,
        "missing_evidence_type": 0,
        "pass": False,
        "assumptions": [],
    }
    issues = []

    # Check file exists
    if not file_path.exists():
        issues.append("File not found")
        result["assumptions"].append("File missing")
        return result, issues
    result["exists"] = True

    # Parse JSON
    try:
        with open(file_path) as f:
            ir = json.load(f)
        result["valid_json"] = True
    except json.JSONDecodeError as e:
        issues.append(f"Invalid JSON: {e}")
        return result, issues

    # Check top-level fields
    for field in REQUIRED_TOP_LEVEL:
        if field not in ir:
            issues.append(f"Missing top-level field: {field}")

    # Check params is empty dict
    if ir.get("params") != {}:
        issues.append(f"params should be empty dict, got: {ir.get('params')}")

    # Count objects, scripts, links, rules
    objects = ir.get("objects", [])
    scripts = ir.get("scripts", [])
    links = ir.get("links", [])
    rules = ir.get("rules", [])

    result["objects_count"] = len(objects)
    result["scripts_count"] = len(scripts)
    result["links_count"] = len(links)
    result["rules_count"] = len(rules)

    # Check rules non-empty
    if len(rules) == 0:
        issues.append("rules is empty")

    # Check all rules have evidence_type
    missing_et = 0
    for rule in rules:
        if "evidence_type" not in rule:
            missing_et += 1
        elif rule["evidence_type"] not in ("direct_code", "scene_override", "inferred"):
            issues.append(f"Rule {rule.get('id', '?')} has invalid evidence_type: {rule['evidence_type']}")
    result["missing_evidence_type"] = missing_et
    if missing_et > 0:
        issues.append(f"{missing_et} rules missing evidence_type")

    # Check every scripts[].object_id exists in objects[].id
    object_ids = {obj["id"] for obj in objects}
    unresolved = 0
    for script in scripts:
        if script.get("object_id") and script["object_id"] not in object_ids:
            unresolved += 1
            # Only log first few
            if unresolved <= 3:
                issues.append(f"Script {script['id']} references object_id {script['object_id']} not in objects")
    result["unresolved_object_ids"] = unresolved
    if unresolved > 3:
        issues.append(f"...and {unresolved - 3} more unresolved object_ids")

    # Check link sources/targets reference valid IDs
    valid_ids = object_ids | {s["id"] for s in scripts} | {"scene"}
    bad_links = 0
    for link in links:
        if link.get("source") not in valid_ids:
            bad_links += 1
        if link.get("target") not in valid_ids:
            bad_links += 1
    if bad_links > 0:
        issues.append(f"{bad_links} link source/target references not found in objects/scripts")
        result["assumptions"].append(f"{bad_links} dangling link refs")

    # Check no placeholder IDs
    for obj in objects:
        if "circle_all" in str(obj.get("id", "")).lower():
            issues.append(f"Placeholder ID found: {obj['id']}")

    # Determine pass/fail
    critical_issues = [i for i in issues if "missing" in i.lower() or "empty" in i.lower() or "invalid" in i.lower()]
    result["pass"] = (
        result["valid_json"]
        and result["rules_count"] > 0
        and result["missing_evidence_type"] == 0
        and result["unresolved_object_ids"] == 0
    )

    if not result["pass"] and not result["assumptions"]:
        result["assumptions"] = issues[:2] if issues else ["validation failed"]

    return result, issues


def main():
    print("Runtime IR Batch Validation")
    print("=" * 60)

    results = []
    all_issues = {}
    passed = 0
    failed = 0

    for scene_name in ALL_SCENES:
        result, issues = validate_scene(scene_name)
        results.append(result)
        all_issues[scene_name] = issues

        status = "PASS" if result["pass"] else "FAIL"
        if result["pass"]:
            passed += 1
        else:
            failed += 1

        detail = f"obj={result['objects_count']} scr={result['scripts_count']} lnk={result['links_count']} rul={result['rules_count']}"
        if result["unresolved_object_ids"] > 0:
            detail += f" unresolved={result['unresolved_object_ids']}"
        if result["missing_evidence_type"] > 0:
            detail += f" missing_et={result['missing_evidence_type']}"
        print(f"  {status}  {scene_name} -- {detail}")
        if issues:
            for issue in issues[:3]:
                print(f"         {issue}")

    print(f"\n{'=' * 60}")
    print(f"Total: {passed} passed, {failed} failed out of {len(ALL_SCENES)}")

    # Write JSON report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "validation_version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_scenes": len(ALL_SCENES),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    json_path = REPORT_DIR / "runtime_ir_batch_validation_v1.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON report: {json_path}")

    # Write markdown summary
    md_lines = [
        "# Runtime IR Batch Validation Report v1",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Total scenes:** {report['total_scenes']}",
        f"**Passed:** {passed}  |  **Failed:** {failed}",
        "",
        "## Per-Scene Results",
        "",
        "| Scene | Objects | Scripts | Links | Rules | Unresolved | Missing ET | Status |",
        "|-------|---------|---------|-------|-------|------------|------------|--------|",
    ]
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        md_lines.append(
            f"| {r['scene']} | {r['objects_count']} | {r['scripts_count']} | "
            f"{r['links_count']} | {r['rules_count']} | {r['unresolved_object_ids']} | "
            f"{r['missing_evidence_type']} | {status} |"
        )

    # Top failure reasons
    if failed > 0:
        md_lines.extend(["", "## Failure Reasons", ""])
        for scene_name, issues in all_issues.items():
            if issues:
                md_lines.append(f"**{scene_name}:**")
                for issue in issues:
                    md_lines.append(f"- {issue}")
                md_lines.append("")

    md_path = REPORT_DIR / "runtime_ir_batch_validation_v1.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"Markdown report: {md_path}")


if __name__ == "__main__":
    main()
