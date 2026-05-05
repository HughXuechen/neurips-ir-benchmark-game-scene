#!/usr/bin/env python3
"""
Verification script for parsed Unity scene JSON outputs.
"""

import json
import re
from pathlib import Path


def count_unity_headers(unity_path):
    """Count the number of block headers in a .unity file."""
    with open(unity_path, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = re.compile(r'^--- !u!\d+ &\d+\s*$', re.MULTILINE)
    return len(pattern.findall(content))


def verify_scene(json_path, unity_path):
    """Verify a single parsed JSON against its source .unity file."""
    scene_name = json_path.stem.replace('_parsed', '')
    errors = []
    warnings = []

    # Load JSON
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 1. Verify top-level keys
    required_top_keys = {'scene', 'blocksByType', 'sortInfo'}
    missing_top = required_top_keys - set(data.keys())
    if missing_top:
        errors.append(f"Missing top-level keys: {missing_top}")

    # Verify sortInfo structure
    if 'sortInfo' in data:
        sort_info = data['sortInfo']
        if 'strategy' not in sort_info:
            errors.append("sortInfo.strategy missing")
        if 'nameResolution' not in sort_info:
            errors.append("sortInfo.nameResolution missing")

    # Collect all blocks
    all_blocks = []
    blocks_by_type = data.get('blocksByType', {})
    for type_name, blocks in blocks_by_type.items():
        for block in blocks:
            all_blocks.append((type_name, block))

    # 2. Verify block fields
    required_block_fields = {'header', 'classID', 'fileID', 'type', 'name', 'data'}
    missing_field_examples = []
    for type_name, block in all_blocks:
        missing = required_block_fields - set(block.keys())
        if missing and len(missing_field_examples) < 3:
            missing_field_examples.append(f"Block fileID={block.get('fileID', '?')}: missing {missing}")

    if missing_field_examples:
        errors.extend(missing_field_examples)

    # 3. Validate header format and consistency
    header_mismatch_examples = []
    header_pattern = re.compile(r'^--- !u!(\d+) &(\d+)$')
    for type_name, block in all_blocks:
        header = block.get('header', '')
        class_id = block.get('classID')
        file_id = block.get('fileID')

        match = header_pattern.match(header)
        if not match:
            if len(header_mismatch_examples) < 3:
                header_mismatch_examples.append(f"Invalid header format: '{header}'")
        else:
            parsed_class_id = int(match.group(1))
            parsed_file_id = int(match.group(2))
            if parsed_class_id != class_id or parsed_file_id != file_id:
                if len(header_mismatch_examples) < 3:
                    header_mismatch_examples.append(
                        f"Header mismatch: header={header}, classID={class_id}, fileID={file_id}"
                    )

    if header_mismatch_examples:
        errors.extend(header_mismatch_examples)

    # 4. Validate type equals top-level key in data
    type_data_mismatch_examples = []
    for type_name, block in all_blocks:
        block_type = block.get('type')
        block_data = block.get('data', {})

        if not isinstance(block_data, dict):
            if len(type_data_mismatch_examples) < 3:
                type_data_mismatch_examples.append(
                    f"Block fileID={block.get('fileID')}: data is not a dict"
                )
            continue

        data_keys = list(block_data.keys())
        if len(data_keys) == 0:
            if len(type_data_mismatch_examples) < 3:
                type_data_mismatch_examples.append(
                    f"Block fileID={block.get('fileID')}: data is empty"
                )
        elif data_keys[0] != block_type:
            if len(type_data_mismatch_examples) < 3:
                type_data_mismatch_examples.append(
                    f"Block fileID={block.get('fileID')}: type={block_type}, but data top key={data_keys[0]}"
                )

    if type_data_mismatch_examples:
        errors.extend(type_data_mismatch_examples)

    # 5. Validate sorting per type
    sorting_violations = []
    for type_name, blocks in blocks_by_type.items():
        for i in range(len(blocks) - 1):
            curr = blocks[i]
            next_block = blocks[i + 1]

            curr_name = curr.get('name', '').lower()
            next_name = next_block.get('name', '').lower()
            curr_file_id = curr.get('fileID', 0)
            next_file_id = next_block.get('fileID', 0)

            # Compare: first by name (case-insensitive), then by fileID
            if curr_name > next_name:
                if len(sorting_violations) < 3:
                    sorting_violations.append(
                        f"{type_name}: '{curr.get('name')}' should come after '{next_block.get('name')}'"
                    )
            elif curr_name == next_name and curr_file_id > next_file_id:
                if len(sorting_violations) < 3:
                    sorting_violations.append(
                        f"{type_name}: same name '{curr.get('name')}', fileID {curr_file_id} > {next_file_id}"
                    )

    if sorting_violations:
        errors.extend(sorting_violations)

    # 6. Cross-check block count with .unity file
    json_block_count = len(all_blocks)
    unity_block_count = count_unity_headers(unity_path)

    count_match = json_block_count == unity_block_count

    # Generate report
    print(f"\n{'='*60}")
    print(f"Scene: {scene_name}")
    print(f"{'='*60}")
    print(f"Block count: JSON={json_block_count}, .unity={unity_block_count} ", end="")
    if count_match:
        print("✓")
    else:
        print(f"✗ (difference: {json_block_count - unity_block_count})")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
    else:
        print("\nAll checks passed ✓")

    return len(errors) == 0 and count_match


def main():
    root = Path(__file__).resolve().parents[2]
    base_dir = root / 'data' / 'processed' / 'scene_analysis'
    unity_dir = root / 'data' / 'raw' / 'unity' / 'Assets' / 'Scenes' / 'Goal'

    scenes = [
        ('1_Ownership_parsed.json', '1_Ownership.unity'),
        ('11_Delivery_parsed.json', '11_Delivery.unity'),
        ('14_Alignment_new_parsed.json', '14_Alignment_new.unity'),
    ]

    print("Unity Scene JSON Verification")
    print("=" * 60)

    all_passed = True
    for json_name, unity_name in scenes:
        json_path = base_dir / json_name
        unity_path = unity_dir / unity_name

        if not json_path.exists():
            print(f"\nERROR: {json_name} not found")
            all_passed = False
            continue

        if not unity_path.exists():
            print(f"\nERROR: {unity_name} not found")
            all_passed = False
            continue

        if not verify_scene(json_path, unity_path):
            all_passed = False

    print(f"\n{'='*60}")
    if all_passed:
        print("SUMMARY: All scenes passed verification ✓")
    else:
        print("SUMMARY: Some scenes have issues ✗")

    return 0 if all_passed else 1


if __name__ == '__main__':
    exit(main())
