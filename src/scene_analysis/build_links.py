#!/usr/bin/env python3
"""
Step 1.5: Build lightweight reference indices from parsed Unity scene JSON.
Creates fileID-based mappings without semantic inference.
"""

import json
from pathlib import Path
from collections import defaultdict


def build_links(parsed_json_path):
    """
    Build reference links from a parsed scene JSON.
    Returns the links structure and statistics.
    """
    with open(parsed_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    scene_name = data['scene']
    blocks_by_type = data['blocksByType']

    # Initialize mappings
    gameObject_to_transform = {}
    gameObject_to_monobehaviours = defaultdict(list)
    component_to_gameObject = {}
    gameObject_name = {}

    # Stats
    stats = {
        'total_gameobjects': 0,
        'total_transforms': 0,
        'total_monobehaviours': 0,
    }

    # 1. Build gameObject_name from GameObject blocks
    for block in blocks_by_type.get('GameObject', []):
        file_id = block['fileID']
        go_data = block['data'].get('GameObject', {})
        m_name = go_data.get('m_Name', '')
        gameObject_name[str(file_id)] = m_name
        stats['total_gameobjects'] += 1

    # 2. Process all block types to find components with m_GameObject
    for type_name, blocks in blocks_by_type.items():
        if type_name == 'GameObject':
            continue  # Already processed

        for block in blocks:
            file_id = block['fileID']
            block_data = block['data'].get(type_name, {})

            # Check if this block has m_GameObject reference
            m_gameobject = block_data.get('m_GameObject')
            if isinstance(m_gameobject, dict) and 'fileID' in m_gameobject:
                go_file_id = m_gameobject['fileID']

                # Skip if fileID is 0 (null reference)
                if go_file_id == 0:
                    continue

                # Add to component_to_gameObject
                component_to_gameObject[str(file_id)] = str(go_file_id)

                # Special handling for Transform (including RectTransform)
                if type_name in ('Transform', 'RectTransform'):
                    gameObject_to_transform[str(go_file_id)] = str(file_id)
                    stats['total_transforms'] += 1

                # Special handling for MonoBehaviour
                elif type_name == 'MonoBehaviour':
                    gameObject_to_monobehaviours[str(go_file_id)].append(str(file_id))
                    stats['total_monobehaviours'] += 1

    # Convert defaultdict to regular dict
    gameObject_to_monobehaviours = dict(gameObject_to_monobehaviours)

    # Build output structure
    output = {
        'scene': scene_name,
        'links': {
            'gameObject_to_transform': gameObject_to_transform,
            'gameObject_to_monobehaviours': gameObject_to_monobehaviours,
            'component_to_gameObject': component_to_gameObject,
            'gameObject_name': gameObject_name,
        }
    }

    # Add mapping sizes to stats
    stats['gameObject_to_transform_count'] = len(gameObject_to_transform)
    stats['gameObject_to_monobehaviours_count'] = len(gameObject_to_monobehaviours)
    stats['component_to_gameObject_count'] = len(component_to_gameObject)
    stats['gameObject_name_count'] = len(gameObject_name)

    return output, stats


def main():
    base_dir = Path(__file__).parent

    scenes = [
        '1_Ownership',
        '11_Delivery',
        '14_Alignment_new',
    ]

    print('Step 1.5: Building Reference Links')
    print('=' * 60)

    for scene_name in scenes:
        input_path = base_dir / f'{scene_name}_parsed.json'
        output_path = base_dir / f'{scene_name}_links.json'

        if not input_path.exists():
            print(f'\nWARNING: {input_path.name} not found, skipping')
            continue

        # Build links
        output, stats = build_links(input_path)

        # Write output
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Print summary
        print(f'\n{scene_name}:')
        print(f'  Total GameObjects: {stats["total_gameobjects"]}')
        print(f'  Total Transforms: {stats["total_transforms"]}')
        print(f'  Total MonoBehaviours: {stats["total_monobehaviours"]}')
        print(f'  Mapping sizes:')
        print(f'    gameObject_to_transform: {stats["gameObject_to_transform_count"]}')
        print(f'    gameObject_to_monobehaviours: {stats["gameObject_to_monobehaviours_count"]}')
        print(f'    component_to_gameObject: {stats["component_to_gameObject_count"]}')
        print(f'    gameObject_name: {stats["gameObject_name_count"]}')
        print(f'  Output: {output_path.name}')

    print('\n' + '=' * 60)
    print('Done.')


if __name__ == '__main__':
    main()
