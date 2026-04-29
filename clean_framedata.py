"""
Transforms raw frame_data.json into a clean, calculator-ready JSON.

Input:  output/frame_data.json  (produced by scrape_framedata.py)
Output: output/frame_data_clean.json

Each move entry will look like:
{
  "move": "cl.A",
  "startup": 4,
  "active": 3,
  "on_block": 1,
  "on_block_feint": null   # populated when a feint value exists
}
"""

import json
import re
from pathlib import Path


def parse_int(value: str) -> int | None:
    """Extract the first signed integer from a string."""
    if not value or not isinstance(value, str):
        return None
    # Skip placeholder values like '+# (-# Feint)'
    if '#' in value:
        return None
    match = re.search(r'([+-]?\d+)', value)
    return int(match.group(1)) if match else None


def parse_on_block(value: str) -> tuple[int | None, int | None]:
    """
    Parse on-block value and optional feint variant.
    Returns (on_block, on_block_feint).

    Handles:
      '+1 (-3 Feint)'                    → (1, -3)
      '+1 / -7 (feint)'                  → (1, -7)
      '-8 (±0 Feint)'                    → (-8, 0)
      '+3~+7 (-6~-3 Feint)'              → (3, -6)   first number of each range
      '+0 (brake 1),+0 (brake 2), -8'   → (-8, None) last number is regular value
      '+1'                               → (1, None)
    """
    if not value or not isinstance(value, str):
        return None, None
    if '#' in value:
        return None, None

    # Normalise ±0 → 0
    value = value.replace('±', '')

    # Format: 'VALUE / FEINT_VALUE (feint)'
    slash = re.match(r'\s*([+-]?\d+)\s*/\s*([+-]?\d+)\s*\(feint\)', value, re.IGNORECASE)
    if slash:
        return int(slash.group(1)), int(slash.group(2))

    # Multi-brake format: '+0 (brake 1),+0 (brake 2), -8'
    # Regular on_block is the last integer; feint is not present here
    if re.search(r'\([Bb]rake\s+\d+\)', value):
        all_nums = re.findall(r'([+-]?\d+)', value)
        return (int(all_nums[-1]) if all_nums else None), None

    # Format: 'VALUE (FEINT_VALUE ...Feint...)'
    normal_match = re.search(r'([+-]?\d+)', value)
    normal = int(normal_match.group(1)) if normal_match else None

    feint_match = re.search(r'\(([+-]?\d+)[^)]*[Ff]eint\)', value)
    feint = int(feint_match.group(1)) if feint_match else None

    return normal, feint


def parse_brake(value: str) -> int | None:
    """
    Extract on_block_brake from an on_block string. Returns None if no brake data.

    Handles:
      '-4 (-2 Brake)'                    → -2
      '-2 / -5 Brake'                    → -5
      '+0 (brake 1),+0 (brake 2), -8'   →  0   (first brake value; both identical for Chun-Li)
    """
    if not value or not isinstance(value, str):
        return None
    if '#' in value:
        return None

    value = value.replace('±', '')

    # Multi-brake: '+0 (brake 1),+0 (brake 2), -8' — first brake value
    multi = re.search(r'([+-]?\d+)\s*\([Bb]rake\s+\d+\)', value)
    if multi:
        return int(multi.group(1))

    # Slash format: 'VALUE / BRAKE_VALUE Brake' (no parentheses around "Brake")
    slash_brake = re.match(r'\s*[+-]?\d+\s*/\s*([+-]?\d+)\s+[Bb]rake', value, re.IGNORECASE)
    if slash_brake:
        return int(slash_brake.group(1))

    # Standard: 'VALUE (-N Brake)'
    brake_match = re.search(r'\(([+-]?\d+)[^)]*[Bb]rake\)', value)
    if brake_match:
        return int(brake_match.group(1))

    return None


def is_name_row(row: dict) -> bool:
    """A name row has exactly one key and its value doesn't start with 'Damage'."""
    return len(row) == 1 and not list(row.values())[0].startswith("Damage")


def is_header_row(row: dict) -> bool:
    """A header row has col_3 containing the word 'Startup'."""
    return "Startup" in row.get("col_3", "")


def extract_move_name(name_row_value: str) -> str:
    """
    The name row value looks like 'cl.A cl.A close A' or '236A Sonic Sword'.
    The move notation is always the first token.
    """
    return name_row_value.strip().split()[0] if name_row_value.strip() else "?"


def process_character(raw: dict) -> list[dict]:
    """
    Walk through all rows for a character and extract clean move data.
    Returns a list of move dicts with move, startup, active, on_block.
    """
    rows = raw.get("moves", {}).get("Uncategorized", [])
    moves = []
    current_move_name = None

    for row in rows:
        if is_name_row(row):
            current_move_name = extract_move_name(list(row.values())[0])
            # Rename universal throw notations
            if current_move_name == 'AB':
                current_move_name = 'Front Throw'
            elif current_move_name == '4AB':
                current_move_name = 'Back Throw'
        elif is_header_row(row):
            pass  # skip header description rows
        elif current_move_name and len(row) > 1:
            startup              = parse_int(row.get("col_3", ""))
            active               = parse_int(row.get("col_4", ""))
            on_hit, on_hit_feint = parse_on_block(row.get("col_6", ""))
            on_hit_brake         = parse_brake(row.get("col_6", ""))
            on_block, on_block_feint = parse_on_block(row.get("col_7", ""))
            on_block_brake       = parse_brake(row.get("col_7", ""))

            # Include moves with at least startup + on_block OR startup + on_hit (throws)
            if startup is not None and (on_block is not None or on_hit is not None):
                entry = {
                    "move":    current_move_name,
                    "startup": startup,
                    "active":  active,
                }
                if on_block is not None:
                    entry["on_block"] = on_block
                if on_block_feint is not None:
                    entry["on_block_feint"] = on_block_feint
                if on_block_brake is not None:
                    entry["on_block_brake"] = on_block_brake
                if on_hit is not None:
                    entry["on_hit"] = on_hit
                if on_hit_feint is not None:
                    entry["on_hit_feint"] = on_hit_feint
                if on_hit_brake is not None:
                    entry["on_hit_brake"] = on_hit_brake
                moves.append(entry)
            # Reset so multi-row moves don't duplicate under the same name
            current_move_name = None

    return moves


# ── Combination attack constants ──────────────────────────────
# Wiki input names that map to each stage of the combination attack
_COMBO_1ST  = {'cl.AC', '5AC'}
_COMBO_2ND  = {'cl.ACC', '5ACC', 'cl.AC/C', '5AC/C'}
_COMBO_CC   = {'cl.AC/CC', '5AC/CC'}          # 3 instances → Standing, Overhead, Low
_COMBO_DROP = {'cl.AC/CC/D', '5AC/CC/D'}      # stray wiki entries — replaced by CC mapping

# Final friendly display names in order
_COMBO_NAMES = [
    'Combination Attack 1st Hit',
    'Combination Attack 2nd Hit',
    'Full Combination Attack Standing',
    'Full Combination Attack Overhead',
    'Full Combination Attack Low',
]

# Kevin Rian's values used as the template for characters with no combo data
_KEVIN_TEMPLATE = [
    {'move': 'Combination Attack 1st Hit',       'startup': 7,  'active': 3, 'on_block': -2},
    {'move': 'Combination Attack 2nd Hit',       'startup': 8,  'active': 4, 'on_block': -4},
    {'move': 'Full Combination Attack Standing', 'startup': 10, 'active': 5, 'on_block': -8},
    {'move': 'Full Combination Attack Overhead', 'startup': 22, 'active': 4, 'on_block': 2},
    {'move': 'Full Combination Attack Low',      'startup': 9,  'active': 3, 'on_block': -11},
]

# Characters whose combo data is missing from the wiki — use Kevin's template
_MISSING_COMBO = {
    'Gato', 'Kim Dong Hwan', 'Kim Jae Hoon', 'Cristiano Ronaldo',
    'Kain R. Heinlein', 'Hokutomaru', 'Mai Shiranui', 'Marco Rodrigues',
    'Nightmare Geese',
}

# The 3 CC instances map to: Standing (1st), Overhead (2nd), Low (3rd)
_CC_SLOT_NAMES = [
    'Full Combination Attack Standing',
    'Full Combination Attack Overhead',
    'Full Combination Attack Low',
]


def apply_combo_fixes(clean: dict) -> dict:
    """
    Post-process the clean data to normalise combination attack entries:
    - Rename wiki input notations to friendly display names
    - Drop stray cl.AC/CC/D wiki rows (replaced by the 3 CC slot mapping)
    - Inject Kevin's template for characters whose combo data is absent
    """
    for char, moves in clean.items():

        # Characters with missing combo data: append Kevin's template
        if char in _MISSING_COMBO:
            clean[char] = moves + [dict(t) for t in _KEVIN_TEMPLATE]
            continue

        has_combo = any(m['move'] in _COMBO_CC or m['move'] in _COMBO_1ST for m in moves)
        if not has_combo:
            continue

        new_moves = []
        cc_count  = 0

        for m in moves:
            mv = m['move']
            if mv in _COMBO_1ST:
                new_moves.append({**m, 'move': 'Combination Attack 1st Hit'})
            elif mv in _COMBO_2ND:
                new_moves.append({**m, 'move': 'Combination Attack 2nd Hit'})
            elif mv in _COMBO_CC:
                if cc_count < 3:
                    new_moves.append({**m, 'move': _CC_SLOT_NAMES[cc_count]})
                    cc_count += 1
                # extra CC rows beyond 3 are silently dropped
            elif mv in _COMBO_DROP:
                pass  # drop — superseded by the CC slot mapping
            else:
                new_moves.append(m)

        clean[char] = new_moves

    return clean


def main():
    raw_path = Path("output/frame_data.json")
    out_path = Path("output/frame_data_clean.json")

    with open(raw_path, encoding="utf-8") as f:
        raw_data = json.load(f)

    EXCLUDE = {"Template"}

    clean = {}
    for char in raw_data:
        name = char["character"]
        if name in EXCLUDE:
            continue
        moves = process_character(char)
        if moves:
            clean[name] = moves
            print(f"  {name}: {len(moves)} moves")
        else:
            print(f"  {name}: no data (page may not be filled in yet)")

    clean = apply_combo_fixes(clean)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)

    total = sum(len(v) for v in clean.values())
    print(f"\nSaved {len(clean)} characters, {total} total moves -> {out_path}")


if __name__ == "__main__":
    main()
