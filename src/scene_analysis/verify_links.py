#!/usr/bin/env python3
"""
Quick sanity check for Step 1.5 link outputs.
Randomly samples GameObjects and components to verify correctness.
"""

import json
import random
from pathlib import Path


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_block_by_fileid(blocks_by_type, file_id):
    """Find a block by its fileID across all types."""
    for type_name, blocks in blocks_by_type.items():
        for block in blocks:
            if block['fileID'] == file_id:
                return block, type_name
    return None, None


def verify_scene(parsed_path, links_path):
    """Verify links for a single scene."""
    parsed = load_json(parsed_path)
    links = load_json(links_path)

    scene_name = links['scene']
    blocks_by_type = parsed['blocksByType']
    link_data = links['links']

    errors = []
    checks = []

    # Get available GameObjects
    go_names = link_data['gameObject_name']
    go_to_transform = link_data['gameObject_to_transform']
    go_to_mbs = link_data['gameObject_to_monobehaviours']
    comp_to_go = link_data['component_to_gameObject']

    # Task 1: Randomly pick 2 GameObjects and verify
    go_ids = list(go_names.keys())
    sample_gos = random.sample(go_ids, min(2, len(go_ids)))

    for go_id in sample_gos:
        go_name = go_names[go_id]
        go_file_id = int(go_id)

        # Verify Transform
        if go_id in go_to_transform:
            transform_id = int(go_to_transform[go_id])
            block, type_name = get_block_by_fileid(blocks_by_type, transform_id)

            if block is None:
                errors.append(f"GO '{go_name}': Transform {transform_id} not found in parsed data")
            else:
                # Check m_GameObject.fileID
                block_data = block['data'].get(type_name, {})
                m_go = block_data.get('m_GameObject', {})
                ref_go_id = m_go.get('fileID')

                if ref_go_id == go_file_id:
                    checks.append(f"GO '{go_name}' ({go_id}): Transform {transform_id} ✓")
                else:
                    errors.append(f"GO '{go_name}': Transform m_GameObject.fileID={ref_go_id}, expected {go_file_id}")
        else:
            checks.append(f"GO '{go_name}' ({go_id}): No Transform (OK if prefab)")

        # Verify MonoBehaviours
        if go_id in go_to_mbs:
            mb_ids = go_to_mbs[go_id]
            mb_ok = True
            for mb_id in mb_ids:
                mb_file_id = int(mb_id)
                block, type_name = get_block_by_fileid(blocks_by_type, mb_file_id)

                if block is None:
                    errors.append(f"GO '{go_name}': MonoBehaviour {mb_id} not found")
                    mb_ok = False
                else:
                    block_data = block['data'].get(type_name, {})
                    m_go = block_data.get('m_GameObject', {})
                    ref_go_id = m_go.get('fileID')

                    if ref_go_id != go_file_id:
                        errors.append(f"GO '{go_name}': MB {mb_id} m_GameObject.fileID={ref_go_id}, expected {go_file_id}")
                        mb_ok = False

            if mb_ok:
                checks.append(f"GO '{go_name}' ({go_id}): {len(mb_ids)} MonoBehaviours ✓")
        else:
            checks.append(f"GO '{go_name}' ({go_id}): No MonoBehaviours")

    # Task 2: Randomly pick 2 components and verify
    comp_ids = list(comp_to_go.keys())
    sample_comps = random.sample(comp_ids, min(2, len(comp_ids)))

    for comp_id in sample_comps:
        expected_go_id = int(comp_to_go[comp_id])
        comp_file_id = int(comp_id)

        block, type_name = get_block_by_fileid(blocks_by_type, comp_file_id)

        if block is None:
            errors.append(f"Component {comp_id}: not found in parsed data")
        else:
            block_data = block['data'].get(type_name, {})
            m_go = block_data.get('m_GameObject', {})
            ref_go_id = m_go.get('fileID')

            go_name = go_names.get(str(expected_go_id), '?')

            if ref_go_id == expected_go_id:
                checks.append(f"Component {comp_id} ({type_name}): → GO '{go_name}' ✓")
            else:
                errors.append(f"Component {comp_id}: m_GameObject.fileID={ref_go_id}, expected {expected_go_id}")

    # Print report
    print(f"\n{'='*50}")
    print(f"Scene: {scene_name}")
    print(f"{'='*50}")

    print("\nGameObject checks:")
    for check in [c for c in checks if 'GO ' in c]:
        print(f"  {check}")

    print("\nComponent checks:")
    for check in [c for c in checks if 'Component' in c]:
        print(f"  {check}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  ✗ {err}")
    else:
        print("\n✓ Quick check passed")

    return len(errors) == 0


def main():
    random.seed(42)  # Reproducible sampling

    base_dir = Path(__file__).parent

    scenes = ['1_Ownership', '11_Delivery', '14_Alignment_new']

    print("Step 1.5 Links Sanity Check")
    print("=" * 50)

    all_passed = True
    for scene in scenes:
        parsed_path = base_dir / f'{scene}_parsed.json'
        links_path = base_dir / f'{scene}_links.json'

        if not parsed_path.exists() or not links_path.exists():
            print(f"\nWARNING: Missing files for {scene}")
            all_passed = False
            continue

        if not verify_scene(parsed_path, links_path):
            all_passed = False

    print(f"\n{'='*50}")
    if all_passed:
        print("SUMMARY: All scenes passed ✓")
    else:
        print("SUMMARY: Some checks failed ✗")


if __name__ == '__main__':
    main()
