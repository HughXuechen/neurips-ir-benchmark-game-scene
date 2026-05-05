#!/usr/bin/env python3
"""
Unity Scene Parser - Step 1
Parses .unity files into JSON with blocks grouped by type and sorted by name.
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict


def parse_unity_yaml_value(value_str):
    """Parse a YAML value string, handling Unity's inline object notation."""
    value_str = value_str.strip()

    # Empty string
    if value_str == '':
        return ''

    # Null
    if value_str in ('null', '~'):
        return None

    # Boolean
    if value_str.lower() == 'true':
        return True
    if value_str.lower() == 'false':
        return False

    # Inline object like {fileID: 0} or {r: 0.5, g: 0.5, b: 0.5, a: 1}
    if value_str.startswith('{') and value_str.endswith('}'):
        inner = value_str[1:-1].strip()
        if not inner:
            return {}
        result = {}
        # Split by comma, but handle nested values
        parts = re.split(r',\s*(?=[a-zA-Z_])', inner)
        for part in parts:
            if ':' in part:
                k, v = part.split(':', 1)
                result[k.strip()] = parse_unity_yaml_value(v.strip())
        return result

    # Inline array like [1, 2, 3]
    if value_str.startswith('[') and value_str.endswith(']'):
        inner = value_str[1:-1].strip()
        if not inner:
            return []
        # Simple array parsing
        parts = inner.split(',')
        return [parse_unity_yaml_value(p.strip()) for p in parts]

    # Number (int or float)
    # But be careful with hex-like strings (GUIDs) that contain letters
    # A GUID like "0000000000000000e000000000000000" should stay as string
    # Only parse as number if it matches a strict numeric pattern
    # Also, very long numeric-looking strings (like GUIDs) should stay as strings
    if len(value_str) <= 20:  # Reasonable length for a number
        if re.match(r'^-?\d+$', value_str):
            # Pure integer
            return int(value_str)
        if re.match(r'^-?\d+\.\d*$', value_str) or re.match(r'^-?\.\d+$', value_str):
            # Float with decimal point
            return float(value_str)
        if re.match(r'^-?\d+(\.\d*)?[eE][+-]?\d+$', value_str):
            # Scientific notation (strict: requires proper format)
            return float(value_str)

    # String (may be quoted or unquoted)
    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1]

    return value_str


def parse_yaml_block(lines):
    """
    Parse YAML lines into a nested dictionary.
    Handles Unity's specific YAML format with proper indentation tracking.
    """
    result = {}
    stack = [(0, result)]  # (indent_level, current_dict)

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # Calculate indent (count leading spaces)
        stripped = line.lstrip(' ')
        indent = len(line) - len(stripped)

        # Pop stack to find correct parent
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        current_indent, current_dict = stack[-1]

        # Handle array item (starts with -)
        if stripped.startswith('- '):
            # This is an array item
            content = stripped[2:].strip()

            # Find the parent key that should be an array
            # The current_dict should already have the array
            # We need to append to the most recent array key at parent level

            if content.startswith('{') and content.endswith('}'):
                # Inline object in array
                item = parse_unity_yaml_value(content)
            elif ':' in content:
                # Object starting on same line as -
                key, value = content.split(':', 1)
                key = key.strip()
                value = value.strip()
                if value:
                    item = {key: parse_unity_yaml_value(value)}
                else:
                    item = {key: {}}
                    # Check for nested content
                    stack.append((indent + 2, item[key]))
            else:
                item = parse_unity_yaml_value(content)

            # Find the array to append to
            if isinstance(current_dict, list):
                current_dict.append(item)
            else:
                # Find most recent key that should be array
                # This handles the case where we need to append to a list
                pass  # Handled by the list case above

            i += 1
            continue

        # Handle key: value
        if ':' in stripped:
            colon_idx = stripped.index(':')
            key = stripped[:colon_idx].strip()
            value_part = stripped[colon_idx + 1:].strip()

            if value_part:
                # Value on same line
                current_dict[key] = parse_unity_yaml_value(value_part)
            else:
                # Check next line for array or nested object
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    next_stripped = next_line.lstrip(' ')
                    next_indent = len(next_line) - len(next_stripped)

                    if next_stripped.startswith('- '):
                        # It's an array
                        current_dict[key] = []
                        stack.append((next_indent, current_dict[key]))
                    else:
                        # Nested object
                        current_dict[key] = {}
                        stack.append((next_indent, current_dict[key]))
                else:
                    current_dict[key] = {}

        i += 1

    return result


def parse_yaml_block_simple(yaml_text):
    """
    Simpler line-by-line YAML parser that handles Unity's format.
    """
    lines = yaml_text.split('\n')

    # Stack: list of (indent, container, key_if_pending_array)
    root = {}
    stack = [(-1, root, None)]
    pending_array_key = None

    for line in lines:
        if not line.strip():
            continue

        # Calculate indent
        stripped = line.lstrip(' ')
        indent = len(line) - len(stripped)

        # Pop stack until we find appropriate parent
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        current_indent, current_container, _ = stack[-1]

        # Array item
        if stripped.startswith('- '):
            content = stripped[2:]

            # Determine what container to add to
            if isinstance(current_container, list):
                if content.strip().startswith('{'):
                    current_container.append(parse_unity_yaml_value(content.strip()))
                elif ':' in content:
                    # Object item
                    k, v = content.split(':', 1)
                    k, v = k.strip(), v.strip()
                    if v:
                        obj = {k: parse_unity_yaml_value(v)}
                        current_container.append(obj)
                    else:
                        obj = {k: {}}
                        current_container.append(obj)
                        stack.append((indent + 2, obj[k], None))
                else:
                    current_container.append(parse_unity_yaml_value(content.strip()))
            continue

        # Key: value
        if ':' in stripped:
            colon_pos = stripped.index(':')
            key = stripped[:colon_pos].strip()
            value = stripped[colon_pos + 1:].strip()

            if isinstance(current_container, dict):
                if value:
                    current_container[key] = parse_unity_yaml_value(value)
                else:
                    # Need to look ahead
                    current_container[key] = {}
                    stack.append((indent + 2, current_container[key], key))

    # Post-process: find empty dicts that should be arrays
    # We'll handle this in a second pass

    return root


def parse_yaml_properly(yaml_text):
    """
    More robust YAML parser for Unity files.
    Uses explicit tracking of array vs dict containers with proper nesting.
    """
    lines = yaml_text.split('\n')

    root = {}
    # Stack: (indent, container, is_list)
    # indent is the indent level where this container's CONTENT starts
    stack = [(-2, root, False)]

    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        stripped = line.lstrip(' ')
        indent = len(line) - len(stripped)

        # Pop stack to find the correct parent for this indent level
        # We pop if current indent is less than the indent where the container's content starts
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()

        parent_indent, parent_container, parent_is_list = stack[-1]

        # Array item
        if stripped.startswith('- '):
            content = stripped[2:]

            # If parent is a list, add to it
            if parent_is_list:
                target_list = parent_container
            else:
                # This shouldn't happen in well-formed YAML, but handle it
                i += 1
                continue

            if content.strip().startswith('{'):
                # Inline object
                target_list.append(parse_unity_yaml_value(content.strip()))
            elif ':' in content:
                # Key: value or key: (nested)
                k, v = content.split(':', 1)
                k, v = k.strip(), v.strip()
                if v:
                    target_list.append({k: parse_unity_yaml_value(v)})
                else:
                    new_obj = {k: {}}
                    target_list.append(new_obj)
                    # The content of this nested object starts at indent + len("- ") + 2
                    stack.append((indent + 2, new_obj[k], False))
            else:
                target_list.append(parse_unity_yaml_value(content.strip()))

            i += 1
            continue

        # Regular key: value
        if ':' in stripped:
            colon_pos = stripped.index(':')
            key = stripped[:colon_pos].strip()
            value = stripped[colon_pos + 1:].strip()

            # If we're in a list context but see a regular key, we need to pop back
            # to find the dict container
            while len(stack) > 1 and stack[-1][2]:  # is_list == True
                stack.pop()

            parent_indent, parent_container, parent_is_list = stack[-1]

            if not isinstance(parent_container, dict):
                i += 1
                continue

            if value:
                parent_container[key] = parse_unity_yaml_value(value)
            else:
                # Look ahead to see if it's an array or object
                # Find next non-empty line
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1

                if j < len(lines):
                    next_line = lines[j]
                    next_stripped = next_line.lstrip(' ')
                    next_indent = len(next_line) - len(next_stripped)

                    # In Unity YAML, arrays can be at same indent as key
                    # (e.g., m_Component:\n  - component: ...)
                    # Or arrays can be indented (standard YAML)
                    if next_stripped.startswith('- '):
                        # It's an array - items can be at same indent or greater
                        parent_container[key] = []
                        stack.append((next_indent, parent_container[key], True))
                    elif next_indent > indent:
                        # Nested object (indented more than the key)
                        parent_container[key] = {}
                        stack.append((next_indent, parent_container[key], False))
                    else:
                        # Empty value (next non-empty line is at same or lower indent
                        # and not an array item)
                        parent_container[key] = None
                else:
                    parent_container[key] = None

        i += 1

    return root


def split_unity_file(content):
    """
    Split a Unity YAML file into individual blocks.
    Each block starts with --- !u!<classID> &<fileID>
    Returns list of (header, classID, fileID, yaml_body)
    """
    # Pattern for Unity block headers
    header_pattern = re.compile(r'^--- !u!(\d+) &(\d+)\s*$', re.MULTILINE)

    blocks = []

    # Find all header positions
    matches = list(header_pattern.finditer(content))

    for i, match in enumerate(matches):
        header = match.group(0).strip()
        class_id = int(match.group(1))
        file_id = int(match.group(2))

        # Get the body (from end of this header to start of next, or end of file)
        start_pos = match.end()
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            end_pos = len(content)

        yaml_body = content[start_pos:end_pos].strip()

        blocks.append((header, class_id, file_id, yaml_body))

    return blocks


def get_block_type(parsed_data):
    """Get the type (top-level key) from parsed block data."""
    if isinstance(parsed_data, dict) and len(parsed_data) > 0:
        return list(parsed_data.keys())[0]
    return 'Unknown'


def resolve_name(block_type, block_data, file_id, gameobject_map):
    """
    Resolve the name for a block following the rules:
    1. If type == "GameObject", use data.GameObject.m_Name
    2. Else if data has m_GameObject.fileID, look up referenced GameObject's m_Name
    3. Else use fileID as string

    For PrefabInstance, always use fileID fallback.
    """
    if block_type == 'PrefabInstance':
        return str(file_id)

    if block_type == 'GameObject':
        try:
            return block_data.get('GameObject', {}).get('m_Name', str(file_id))
        except (AttributeError, TypeError):
            return str(file_id)

    # Try to find m_GameObject reference
    try:
        type_data = block_data.get(block_type, {})
        if isinstance(type_data, dict):
            m_gameobject = type_data.get('m_GameObject', {})
            if isinstance(m_gameobject, dict):
                ref_file_id = m_gameobject.get('fileID')
                if ref_file_id and ref_file_id in gameobject_map:
                    return gameobject_map[ref_file_id]
    except (AttributeError, TypeError):
        pass

    return str(file_id)


def parse_scene_file(filepath):
    """
    Parse a Unity .unity scene file and return the structured JSON output.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Get scene name from filename
    scene_name = Path(filepath).stem

    # Split into blocks
    raw_blocks = split_unity_file(content)

    # Parse each block
    parsed_blocks = []
    gameobject_map = {}  # fileID -> m_Name for GameObjects

    for header, class_id, file_id, yaml_body in raw_blocks:
        # Parse the YAML body
        parsed_data = parse_yaml_properly(yaml_body)

        # Get the block type
        block_type = get_block_type(parsed_data)

        # Build gameobject map for name resolution
        if block_type == 'GameObject':
            try:
                name = parsed_data.get('GameObject', {}).get('m_Name', str(file_id))
                gameobject_map[file_id] = name
            except (AttributeError, TypeError):
                gameobject_map[file_id] = str(file_id)

        parsed_blocks.append({
            'header': header,
            'classID': class_id,
            'fileID': file_id,
            'type': block_type,
            'data': parsed_data
        })

    # Resolve names for all blocks
    for block in parsed_blocks:
        block['name'] = resolve_name(
            block['type'],
            block['data'],
            block['fileID'],
            gameobject_map
        )

    # Group by type
    blocks_by_type = defaultdict(list)
    for block in parsed_blocks:
        blocks_by_type[block['type']].append(block)

    # Sort each type group by name (case-insensitive), then by fileID
    for type_name in blocks_by_type:
        blocks_by_type[type_name].sort(
            key=lambda b: (b['name'].lower(), b['fileID'])
        )

    # Build output
    output = {
        'scene': scene_name,
        'blocksByType': dict(blocks_by_type),
        'sortInfo': {
            'strategy': 'type group + name A-Z',
            'nameResolution': 'GameObject.m_Name | linked GameObject name | fileID'
        }
    }

    return output, {t: len(blocks) for t, blocks in blocks_by_type.items()}


def main():
    # Define input and output paths
    root = Path(__file__).resolve().parents[2]
    input_dir = root / 'data' / 'raw' / 'unity' / 'Assets' / 'Scenes' / 'Goal'
    output_dir = root / 'data' / 'processed' / 'scene_analysis'
    output_dir.mkdir(parents=True, exist_ok=True)

    # Scene files to process
    scene_files = [
        '1_Ownership.unity',
        '11_Delivery.unity',
        '14_Alignment_new.unity'
    ]

    print('Unity Scene Parser - Step 1 (Parsing Only)')
    print('=' * 50)

    total_summary = {}

    for scene_file in scene_files:
        input_path = input_dir / scene_file

        if not input_path.exists():
            print(f'WARNING: {scene_file} not found at {input_path}')
            continue

        # Parse the scene
        output_data, block_counts = parse_scene_file(input_path)

        # Write output JSON
        output_filename = output_data['scene'] + '_parsed.json'
        output_path = output_dir / output_filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f'\nProcessed: {scene_file}')
        print(f'  Output: {output_filename}')
        print(f'  Blocks by type:')
        for type_name, count in sorted(block_counts.items()):
            print(f'    {type_name}: {count}')

        total_summary[scene_file] = block_counts

    print('\n' + '=' * 50)
    print('Summary:')
    print(f'  Files written: {len(total_summary)}')
    for scene, counts in total_summary.items():
        total_blocks = sum(counts.values())
        print(f'  {scene}: {total_blocks} total blocks')


if __name__ == '__main__':
    main()
