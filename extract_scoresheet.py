#!/usr/bin/env python3
"""
Extract all structured data from an MKOSZ basketball scoresheet PDF
into a SQLite database.

Tables: match_info, referees, officials, players, personal_fouls,
        team_fouls, timeouts, quarter_scores, running_score
"""

import fitz  # PyMuPDF
import sqlite3
import os
import re
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(SCRIPT_DIR, "hun3k_125657.pdf")
DB_PATH = os.path.join(SCRIPT_DIR, "folyamatos_eredmeny.sqlite")

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

COLOR_MAP = {
    0xFF0000: "red",
    0x000000: "black",
    0x088008: "green",
    0x0000FF: "blue",
}

QUARTER_BY_COLOR = {
    0xFF0000: 1,   # red   → Q1
    0x000000: 2,   # black → Q2
    0x088008: 3,   # green → Q3
    0x0000FF: 4,   # blue  → Q4
}

# Official/league data color (near-blue used for team names, license numbers, etc.)
OFFICIAL_BLUE = 0x0303FF


def color_name(color_int):
    if color_int in COLOR_MAP:
        return COLOR_MAP[color_int]
    best, best_dist = "black", float("inf")
    r, g, b = (color_int >> 16) & 0xFF, (color_int >> 8) & 0xFF, color_int & 0xFF
    for cint, cname in COLOR_MAP.items():
        cr, cg, cb = (cint >> 16) & 0xFF, (cint >> 8) & 0xFF, cint & 0xFF
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_dist:
            best, best_dist = cname, d
    return best


def color_to_quarter(color_int):
    """Map a color int to quarter number (1-4), or None."""
    if color_int in QUARTER_BY_COLOR:
        return QUARTER_BY_COLOR[color_int]
    # Nearest match fallback
    best_q, best_dist = None, float("inf")
    r, g, b = (color_int >> 16) & 0xFF, (color_int >> 8) & 0xFF, color_int & 0xFF
    for cint, q in QUARTER_BY_COLOR.items():
        cr, cg, cb = (cint >> 16) & 0xFF, (cint >> 8) & 0xFF, cint & 0xFF
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_dist:
            best_q, best_dist = q, d
    return best_q


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def collect_chars_in_rect(chars, x_min, x_max, y_min, y_max, color_filter=None):
    """Return chars within the given bounding box, optionally filtered by color."""
    result = []
    for ch in chars:
        if x_min <= ch["x"] <= x_max and y_min <= ch["y"] <= y_max:
            if color_filter is not None and ch["color"] != color_filter:
                continue
            result.append(ch)
    return result


def assemble_text(chars, gap_threshold=2.0):
    """Sort chars by x and join into a string, inserting spaces at large gaps."""
    if not chars:
        return ""
    sorted_chars = sorted(chars, key=lambda c: c["x"])
    text = sorted_chars[0]["c"]
    for i in range(1, len(sorted_chars)):
        gap = sorted_chars[i]["x"] - sorted_chars[i - 1].get("x1", sorted_chars[i - 1]["x"] + 6)
        if gap > gap_threshold:
            text += " "
        text += sorted_chars[i]["c"]
    return text.strip()


def assemble_number(chars):
    """Sort chars by x and concatenate digits into a number string."""
    if not chars:
        return ""
    sorted_chars = sorted(chars, key=lambda c: c["x"])
    return "".join(ch["c"] for ch in sorted_chars).strip()


def is_circled(x, y, circles, tolerance=4):
    """Check if position (x, y) falls inside any circle."""
    for cx0, cy0, cx1, cy1 in circles:
        if cx0 - tolerance <= x <= cx1 + tolerance and cy0 - tolerance <= y <= cy1 + tolerance:
            return True
    return False


# ---------------------------------------------------------------------------
# PDF extraction — common step (all chars + all circles)
# ---------------------------------------------------------------------------

def extract_all_from_pdf(pdf_path):
    """Extract all characters and circles from the first page of the PDF."""
    doc = fitz.open(pdf_path)
    page = doc[0]

    # --- All characters ---
    blocks = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    all_chars = []
    for block in blocks["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span.get("chars", []):
                    x0, y0, x1, y1 = ch["bbox"]
                    if ch["c"].strip():
                        all_chars.append({
                            "c": ch["c"],
                            "x": x0,
                            "y": y0,
                            "x1": x1,
                            "y1": y1,
                            "color": span["color"],
                            "size": span["size"],
                        })

    # --- All circles ---
    drawings = page.get_drawings()
    all_circles = []
    for d in drawings:
        rect = d["rect"]
        x0, y0, x1, y1 = rect
        has_curve = any(item[0] == "c" for item in d["items"])
        w, h = x1 - x0, y1 - y0
        if has_curve and 5 < w < 25 and 5 < h < 25 and abs(w - h) < 5:
            all_circles.append((x0, y0, x1, y1))

    doc.close()
    return all_chars, all_circles


# ---------------------------------------------------------------------------
# Running Score extraction (existing logic, preserved)
# ---------------------------------------------------------------------------

# Column boundaries for the running score table
COL_BOUNDS = [
    # Első félidő — 1. oszlopcsoport (A1-1, A1-2, M1, B1-1, B1-2)
    481, 503, 524, 543, 564,
    # Első félidő — 2. oszlopcsoport (A2-1, A2-2, M2, B2-1, B2-2)
    586, 605, 627, 646, 665,
    # Második félidő — 1. oszlopcsoport
    687, 708, 729, 749, 769,
    # Második félidő — 2. oszlopcsoport
    792, 811, 832, 851, 870,
    # Hosszabbítás — 1. oszlopcsoport
    891, 912, 933, 953, 973,
    # Hosszabbítás — 2. oszlopcsoport
    994, 1014, 1035, 1055, 1076,
    1097,
]

GROUPS = [
    ("Első félidő",    ["A1-1", "A1-2", "M1", "B1-1", "B1-2"]),
    ("Első félidő",    ["A2-1", "A2-2", "M2", "B2-1", "B2-2"]),
    ("Második félidő", ["A1-1", "A1-2", "M1", "B1-1", "B1-2"]),
    ("Második félidő", ["A2-1", "A2-2", "M2", "B2-1", "B2-2"]),
    ("Hosszabbítás",   ["A1-1", "A1-2", "M1", "B1-1", "B1-2"]),
    ("Hosszabbítás",   ["A2-1", "A2-2", "M2", "B2-1", "B2-2"]),
]

COLUMNS = []
_idx = 0
for _gi, (_header, _names) in enumerate(GROUPS):
    for _ci, _cname in enumerate(_names):
        COLUMNS.append((COL_BOUNDS[_idx], COL_BOUNDS[_idx + 1], _header, _cname))
        _idx += 1

ROW_TOP = 306
ROW_HEIGHT = 26.05
NUM_ROWS = 42


def _get_row(y):
    r = int((y - ROW_TOP) / ROW_HEIGHT) + 1
    return max(1, min(r, NUM_ROWS))


def _get_column(x):
    for left, right, header, cname in COLUMNS:
        if left <= x < right:
            return (header, cname)
    return None


def extract_running_score(all_chars, all_circles):
    """Extract the Folyamatos Eredmény table (unchanged logic)."""
    # Filter to running score area
    raw_chars = [ch for ch in all_chars if ch["x"] >= 480 and 300 < ch["y"] < 1410]
    rs_circles = [(x0, y0, x1, y1) for x0, y0, x1, y1 in all_circles
                  if x0 >= 475 and y0 >= 290 and y1 <= 1420]

    cells = {}
    for ch in raw_chars:
        col_info = _get_column(ch["x"])
        if col_info is None:
            continue
        header, cname = col_info
        row = _get_row(ch["y"])
        key = (row, header, cname)
        cells.setdefault(key, []).append((ch["x"], ch["c"], ch["color"]))

    records = []
    for (row, header, cname), char_list in sorted(cells.items()):
        char_list.sort(key=lambda t: t[0])

        tokens = []
        current = []
        for i, (x, c, color) in enumerate(char_list):
            if current and x - char_list[i - 1][0] > 12:
                tokens.append(current)
                current = []
            current.append((x, c, color))
        if current:
            tokens.append(current)

        for token_chars in tokens:
            text = "".join(c for _, c, _ in token_chars)
            color_val = token_chars[0][2]
            for _, c, col in token_chars:
                if c != "-":
                    color_val = col
                    break

            circled = 0
            for cx0, cy0, cx1, cy1 in rs_circles:
                for chx, _, _ in token_chars:
                    if cx0 - 3 <= chx <= cx1 + 3:
                        ch_y = None
                        for rc in raw_chars:
                            if abs(rc["x"] - chx) < 1:
                                ch_y = rc["y"]
                                break
                        if ch_y is not None and cy0 - 3 <= ch_y <= cy1 + 3:
                            circled = 1
                            break
                if circled:
                    break

            records.append({
                "header": header,
                "column": cname,
                "color": color_name(color_val),
                "circled": circled,
                "row_number": row,
                "character": text,
            })

    return records


# ---------------------------------------------------------------------------
# Match info extraction
# ---------------------------------------------------------------------------

def extract_match_info(all_chars):
    """Extract match metadata from header and footer."""
    def blue_text(x_min, x_max, y_min, y_max, gap=2.0):
        chars = collect_chars_in_rect(all_chars, x_min, x_max, y_min, y_max,
                                      color_filter=OFFICIAL_BLUE)
        return assemble_text(chars, gap_threshold=gap)

    # Team names — y≈83-95, A ends ~x=521, B starts ~x=720
    team_a = blue_text(90, 600, 80, 100)
    team_b = blue_text(600, 900, 80, 100)

    # Venue — y≈126-136
    venue = blue_text(200, 500, 123, 140)

    # Match ID — y≈175-185
    match_id = blue_text(20, 200, 172, 190)

    # Date and time — y≈205-215
    match_date = blue_text(200, 360, 202, 220)
    match_time = blue_text(360, 450, 202, 220)

    # Final score — footer y≈1548-1562 (black text, not blue)
    score_chars_a = collect_chars_in_rect(all_chars, 698, 730, 1548, 1565)
    score_a_text = assemble_number([c for c in score_chars_a if c["c"].isdigit()])

    score_chars_b = collect_chars_in_rect(all_chars, 908, 935, 1548, 1565)
    score_b_text = assemble_number([c for c in score_chars_b if c["c"].isdigit()])

    # Winner — y≈1575-1590
    winner = blue_text(650, 900, 1572, 1595)

    # Closure timestamp — y≈1620-1635
    closure = blue_text(900, 1080, 1618, 1640)

    return {
        "match_id": match_id,
        "team_a": team_a,
        "team_b": team_b,
        "venue": venue,
        "match_date": match_date,
        "match_time": match_time,
        "score_a": int(score_a_text) if score_a_text.isdigit() else None,
        "score_b": int(score_b_text) if score_b_text.isdigit() else None,
        "winner": winner,
        "closure_timestamp": closure,
    }


# ---------------------------------------------------------------------------
# Referees extraction
# ---------------------------------------------------------------------------

def extract_referees(all_chars):
    """Extract referee names from the header."""
    referees = []

    # I. Játékvezető — y≈125-135
    name = assemble_text(
        collect_chars_in_rect(all_chars, 580, 800, 122, 138, color_filter=OFFICIAL_BLUE),
        gap_threshold=2.0)
    if name:
        referees.append({"role": "I. Játékvezető", "name": name})

    # II. Játékvezető — y≈145-158
    name = assemble_text(
        collect_chars_in_rect(all_chars, 580, 800, 143, 160, color_filter=OFFICIAL_BLUE),
        gap_threshold=2.0)
    if name:
        referees.append({"role": "II. Játékvezető", "name": name})

    return referees


# ---------------------------------------------------------------------------
# Officials extraction (footer)
# ---------------------------------------------------------------------------

def extract_officials(all_chars):
    """Extract officials (scorer, timekeeper, etc.) from the footer."""
    officials = []
    roles = [
        ("Jegyző",           1414, 1435),
        ("Időmérő",          1462, 1480),
        ("24\"-es időmérő",  1488, 1505),
    ]
    for role, y_min, y_max in roles:
        name = assemble_text(
            collect_chars_in_rect(all_chars, 70, 400, y_min, y_max, color_filter=OFFICIAL_BLUE),
            gap_threshold=2.0)
        if name:
            officials.append({"role": role, "name": name})

    return officials


# ---------------------------------------------------------------------------
# Quarter scores extraction (footer)
# ---------------------------------------------------------------------------

def extract_quarter_scores(all_chars):
    """Extract quarter-by-quarter scores from the footer."""
    scores = []
    # Quarter score rows are at approximately y=1418, 1443, 1468, 1493, 1518
    quarter_rows = [
        ("1", 1413, 1430),
        ("2", 1438, 1455),
        ("3", 1463, 1480),
        ("4", 1488, 1505),
        ("Hosszabbítás", 1513, 1530),
    ]
    for q_label, y_min, y_max in quarter_rows:
        # A score — roughly x 770-800
        a_chars = [c for c in collect_chars_in_rect(all_chars, 750, 810, y_min, y_max)
                   if c["c"].isdigit()]
        a_text = assemble_number(a_chars)
        # B score — roughly x 910-940
        b_chars = [c for c in collect_chars_in_rect(all_chars, 890, 950, y_min, y_max)
                   if c["c"].isdigit()]
        b_text = assemble_number(b_chars)
        scores.append({
            "quarter": q_label,
            "score_a": int(a_text) if a_text.isdigit() else None,
            "score_b": int(b_text) if b_text.isdigit() else None,
        })
    return scores


# ---------------------------------------------------------------------------
# Players extraction
# ---------------------------------------------------------------------------

# Player roster y-ranges (first row top, last row bottom, row height)
TEAM_A_PLAYERS = {"y_start": 430, "y_end": 725, "row_height": 24.5, "max_rows": 12}
TEAM_B_PLAYERS = {"y_start": 1033, "y_end": 1220, "row_height": 24.5, "max_rows": 12}

# Coach y-ranges
TEAM_A_COACH = {"coach_y": (730, 760), "asst_y": (768, 795)}
TEAM_B_COACH = {"coach_y": (1330, 1360), "asst_y": (1358, 1385)}


def extract_players(all_chars, all_circles, team, cfg, coach_cfg):
    """Extract player roster for one team."""
    players = []
    y_start = cfg["y_start"]
    rh = cfg["row_height"]

    for row_idx in range(cfg["max_rows"]):
        y_min = y_start + row_idx * rh
        y_max = y_min + rh

        # License number — x 20-80, blue, size ~13
        license_chars = collect_chars_in_rect(all_chars, 20, 85, y_min, y_max,
                                               color_filter=OFFICIAL_BLUE)
        license_chars = [c for c in license_chars if c["c"].isdigit()]
        if not license_chars:
            continue  # empty row
        license_num = assemble_number(license_chars)

        # Player name — x 95-275, blue (must not overlap with jersey at x≈282)
        name_chars = collect_chars_in_rect(all_chars, 95, 275, y_min, y_max,
                                            color_filter=OFFICIAL_BLUE)
        name = assemble_text(name_chars, gap_threshold=2.0)

        # Jersey number — x 275-330, blue
        jersey_chars = collect_chars_in_rect(all_chars, 275, 330, y_min, y_max,
                                              color_filter=OFFICIAL_BLUE)
        jersey_chars = [c for c in jersey_chars if c["c"].isdigit()]
        jersey_text = assemble_number(jersey_chars)
        jersey_num = int(jersey_text) if jersey_text.isdigit() else None

        # Role detection
        role = "player"
        if "(KAP)" in name or "( KAP)" in name:
            role = "captain"
            name = name.replace("(KAP)", "").replace("( KAP)", "").strip()

        # X marker — x 330-360, any color
        x_chars = [c for c in collect_chars_in_rect(all_chars, 325, 365, y_min, y_max)
                   if c["c"].upper() == "X"]
        entry_quarter = None
        starter = 0
        if x_chars:
            x_ch = x_chars[0]
            entry_quarter = color_to_quarter(x_ch["color"])
            if is_circled(x_ch["x"], x_ch["y"], all_circles):
                starter = 1

        players.append({
            "team": team,
            "license_number": license_num,
            "name": name,
            "jersey_number": jersey_num,
            "role": role,
            "starter": starter,
            "entry_quarter": entry_quarter,
        })

    # Coaches — name and license may be on the same line or different lines
    for coach_role, (y_min, y_max) in [("coach", coach_cfg["coach_y"]),
                                         ("assistant_coach", coach_cfg["asst_y"])]:
        all_blue = collect_chars_in_rect(all_chars, 20, 300, y_min, y_max,
                                          color_filter=OFFICIAL_BLUE)
        if not all_blue:
            continue

        # Group chars by y-line (tolerance 8px)
        all_blue.sort(key=lambda c: (c["y"], c["x"]))
        lines = []
        current_line = [all_blue[0]]
        for i in range(1, len(all_blue)):
            if abs(all_blue[i]["y"] - current_line[0]["y"]) > 8:
                lines.append(current_line)
                current_line = [all_blue[i]]
            else:
                current_line.append(all_blue[i])
        lines.append(current_line)

        if len(lines) >= 2:
            # Multi-line: first line = name, later line(s) = license digits
            name = assemble_text(lines[0], gap_threshold=2.0)
            lic_digits = []
            for ln in lines[1:]:
                lic_digits.extend(c for c in ln if c["c"].isdigit())
            license_num = assemble_number(lic_digits) if lic_digits else None
        else:
            # Single line: name followed by trailing license digits
            text = assemble_text(lines[0], gap_threshold=2.0)
            m = re.match(r'^(.+?)\s+(\d{3,6})$', text)
            if m:
                name = m.group(1).strip()
                license_num = m.group(2)
            else:
                name = text
                license_num = None

        if name:
            players.append({
                "team": team,
                "license_number": license_num,
                "name": name,
                "jersey_number": None,
                "role": coach_role,
                "starter": 0,
                "entry_quarter": None,
            })

    return players


# ---------------------------------------------------------------------------
# Personal fouls extraction
# ---------------------------------------------------------------------------

# 5 foul slots per player, approximate x-boundaries
FOUL_SLOTS_A = [(367, 395), (395, 415), (415, 433), (433, 451), (451, 475)]
FOUL_SLOTS_B = [(362, 393), (393, 415), (415, 435), (435, 453), (453, 475)]


FOUL_CATEGORY_LETTERS = {"T", "U", "B", "C", "D"}


def _parse_foul_slot(all_chars_in_slot, all_circles):
    """Parse a single foul slot and return a dict with foul data, or None if empty.

    A foul slot may contain (per FIBA B.8.3):
    - Main digit(s) (larger size, ~13.4): the minute of the foul
      OR main letters "GD": game disqualification marker
    - Annotation digit (smaller size, ~11.1): free throws awarded (1, 2, or 3)
    - Annotation letter (smaller size, ~11.1):
        - "T"/"U"/"B"/"C"/"D" = foul category (jobb alsó index)
        - "c" = offsetting foul, 42.§ (jobb felső index)
    - Circle around the main digit: offensive foul (támadó hiba)
    """
    # Collect all meaningful chars (digits + letters, skip punctuation/labels)
    slot_chars = [c for c in all_chars_in_slot if c["c"].isdigit() or c["c"].isalpha()]
    if not slot_chars:
        return None

    # Separate by size: main (largest) vs annotation (smaller)
    sizes = set(c["size"] for c in slot_chars)
    if len(sizes) > 1:
        max_size = max(sizes)
        main_chars = [c for c in slot_chars if c["size"] == max_size]
        annotation_chars = [c for c in slot_chars if c["size"] != max_size]
    else:
        main_chars = slot_chars
        annotation_chars = []

    # --- Analyze main characters ---
    main_digits = [c for c in main_chars if c["c"].isdigit()]
    main_letters = [c for c in main_chars if c["c"].isalpha()]

    if main_letters and not main_digits:
        # Slot contains only letters at main size → "GD" marker
        gd_text = "".join(c["c"] for c in sorted(main_letters, key=lambda c: c["x"]))
        if "GD" in gd_text.upper():
            quarter = color_to_quarter(main_letters[0]["color"])
            return {
                "minute": None,
                "quarter": quarter,
                "foul_type": "defensive",
                "foul_category": "GD",
                "free_throws": None,
                "offsetting": 0,
            }
        return None  # Unknown letters, skip

    if not main_digits:
        return None

    minute_text = assemble_number(main_digits)
    quarter = color_to_quarter(main_digits[0]["color"])

    # Foul type: circled = offensive (támadó), not circled = defensive (védő)
    foul_type = "defensive"
    for mc in main_digits:
        if is_circled(mc["x"], mc["y"], all_circles):
            foul_type = "offensive"
            break

    # --- Analyze annotation characters ---
    free_throws = None
    foul_category = None
    offsetting = 0

    ann_digits = [c for c in annotation_chars if c["c"].isdigit()]
    ann_letters = [c for c in annotation_chars if c["c"].isalpha()]

    # Annotation digits → free throws (1, 2, or 3)
    if ann_digits:
        ft_text = assemble_number(ann_digits)
        if ft_text.isdigit():
            free_throws = int(ft_text)

    # Annotation letters → foul category or offsetting
    for lc in ann_letters:
        letter = lc["c"].upper()
        if letter in FOUL_CATEGORY_LETTERS:
            foul_category = letter
        elif lc["c"] == "c":  # lowercase "c" = offsetting (42.§)
            offsetting = 1

    return {
        "minute": minute_text,
        "quarter": quarter,
        "foul_type": foul_type,
        "foul_category": foul_category,
        "free_throws": free_throws,
        "offsetting": offsetting,
    }


def extract_personal_fouls(all_chars, all_circles, team, player_cfg, foul_slots,
                           players_list, coach_cfg=None):
    """Extract personal fouls for one team's players and coaches.

    Each foul slot may contain (per FIBA B.8.3):
    - Main digit(s): minute of the foul
    - Annotation digit: free throws awarded (1, 2, or 3)
    - Annotation letter: foul category (T/U/B/C/D) or offsetting ("c")
    - Circle: offensive foul
    - "GD" text: game disqualification marker
    """
    fouls = []
    y_start = player_cfg["y_start"]
    rh = player_cfg["row_height"]

    # --- Player fouls ---
    team_players = [p for p in players_list if p["team"] == team and p["role"] in ("player", "captain")]

    for pi, player in enumerate(team_players):
        y_min = y_start + pi * rh
        y_max = y_min + rh

        for slot_idx, (x_min, x_max) in enumerate(foul_slots):
            slot_chars = collect_chars_in_rect(all_chars, x_min, x_max, y_min, y_max)
            parsed = _parse_foul_slot(slot_chars, all_circles)
            if parsed is None:
                continue

            fouls.append({
                "team": team,
                "jersey_number": player["jersey_number"],
                "foul_number": slot_idx + 1,
                **parsed,
            })

    # --- Coach fouls (technical fouls: B/C types) ---
    if coach_cfg:
        for coach_role, (cy_min, cy_max) in [("coach", coach_cfg["coach_y"]),
                                               ("assistant_coach", coach_cfg["asst_y"])]:
            # Extend y-range downward: annotation letters (e.g. "C") may be ~15px below the minute
            extended_y_max = cy_max + 20

            for slot_idx, (x_min, x_max) in enumerate(foul_slots):
                slot_chars = collect_chars_in_rect(all_chars, x_min, x_max, cy_min, extended_y_max)
                parsed = _parse_foul_slot(slot_chars, all_circles)
                if parsed is None:
                    continue

                fouls.append({
                    "team": team,
                    "jersey_number": None,  # coaches have no jersey number
                    "foul_number": slot_idx + 1,
                    **parsed,
                })

    return fouls


# ---------------------------------------------------------------------------
# Team fouls extraction
# ---------------------------------------------------------------------------

# Team foul X-mark regions per row
# Row 1 (Q1/Q2): odd quarter x 220-295, even quarter x 330-410
# Row 2 (Q3/Q4): same x ranges

TEAM_FOUL_REGIONS = {
    "A": {
        "rows": [
            {"y_min": 285, "y_max": 310, "q_odd": 1, "q_even": 2},
            {"y_min": 318, "y_max": 345, "q_odd": 3, "q_even": 4},
        ],
    },
    "B": {
        "rows": [
            {"y_min": 888, "y_max": 920, "q_odd": 1, "q_even": 2},
            {"y_min": 920, "y_max": 952, "q_odd": 3, "q_even": 4},
        ],
    },
}


def extract_team_fouls(all_chars, team):
    """Extract team foul counts per quarter."""
    fouls = []
    for row_cfg in TEAM_FOUL_REGIONS[team]["rows"]:
        y_min, y_max = row_cfg["y_min"], row_cfg["y_max"]

        # Odd quarter (left group, x 215-300)
        odd_x = collect_chars_in_rect(all_chars, 215, 300, y_min, y_max)
        odd_count = sum(1 for c in odd_x if c["c"].upper() == "X")
        fouls.append({"team": team, "quarter": row_cfg["q_odd"], "foul_count": odd_count})

        # Even quarter (right group, x 330-410)
        even_x = collect_chars_in_rect(all_chars, 330, 415, y_min, y_max)
        even_count = sum(1 for c in even_x if c["c"].upper() == "X")
        fouls.append({"team": team, "quarter": row_cfg["q_even"], "foul_count": even_count})

    return fouls


# ---------------------------------------------------------------------------
# Timeouts extraction
# ---------------------------------------------------------------------------

TIMEOUT_REGIONS = {
    "A": {
        "rows": [
            {"y_min": 285, "y_max": 310},
            {"y_min": 318, "y_max": 345},
        ],
    },
    "B": {
        "rows": [
            {"y_min": 888, "y_max": 920},
            {"y_min": 920, "y_max": 952},
        ],
    },
}


def extract_timeouts(all_chars, team):
    """Extract timeout events (minute + quarter from color)."""
    timeouts = []

    for row_cfg in TIMEOUT_REGIONS[team]["rows"]:
        y_min, y_max = row_cfg["y_min"], row_cfg["y_max"]
        # Timeout minutes are at x < 130
        chars = collect_chars_in_rect(all_chars, 0, 135, y_min, y_max)
        digit_chars = [c for c in chars if c["c"].isdigit()]
        if not digit_chars:
            continue

        # Group by proximity (separate timeout entries)
        digit_chars.sort(key=lambda c: c["x"])
        groups = []
        current_group = [digit_chars[0]]
        for i in range(1, len(digit_chars)):
            if digit_chars[i]["x"] - digit_chars[i - 1].get("x1", digit_chars[i - 1]["x"] + 8) > 8:
                groups.append(current_group)
                current_group = [digit_chars[i]]
            else:
                current_group.append(digit_chars[i])
        groups.append(current_group)

        for group in groups:
            minute = assemble_number(group)
            quarter = color_to_quarter(group[0]["color"])
            if minute and quarter:
                timeouts.append({"team": team, "quarter": quarter, "minute": minute})

    return timeouts


# ---------------------------------------------------------------------------
# Database writing
# ---------------------------------------------------------------------------

def write_db(db_path, running_score, match_info, referees, officials,
             players, personal_fouls, team_fouls, timeouts, quarter_scores):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # --- running_score (existing) ---
    c.execute("DROP TABLE IF EXISTS running_score")
    c.execute("""
        CREATE TABLE running_score (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            header TEXT NOT NULL,
            column_name TEXT NOT NULL,
            color TEXT NOT NULL,
            circled INTEGER NOT NULL DEFAULT 0,
            row_number INTEGER NOT NULL,
            character TEXT NOT NULL
        )
    """)
    for r in running_score:
        c.execute("INSERT INTO running_score (header, column_name, color, circled, row_number, character) VALUES (?,?,?,?,?,?)",
                  (r["header"], r["column"], r["color"], r["circled"], r["row_number"], r["character"]))

    # --- match_info ---
    c.execute("DROP TABLE IF EXISTS match_info")
    c.execute("""
        CREATE TABLE match_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT, team_a TEXT, team_b TEXT,
            venue TEXT, match_date TEXT, match_time TEXT,
            score_a INTEGER, score_b INTEGER,
            winner TEXT, closure_timestamp TEXT
        )
    """)
    m = match_info
    c.execute("INSERT INTO match_info (match_id, team_a, team_b, venue, match_date, match_time, score_a, score_b, winner, closure_timestamp) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (m["match_id"], m["team_a"], m["team_b"], m["venue"], m["match_date"], m["match_time"],
               m["score_a"], m["score_b"], m["winner"], m["closure_timestamp"]))

    # --- referees ---
    c.execute("DROP TABLE IF EXISTS referees")
    c.execute("CREATE TABLE referees (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, name TEXT NOT NULL)")
    for r in referees:
        c.execute("INSERT INTO referees (role, name) VALUES (?,?)", (r["role"], r["name"]))

    # --- officials ---
    c.execute("DROP TABLE IF EXISTS officials")
    c.execute("CREATE TABLE officials (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, name TEXT NOT NULL)")
    for o in officials:
        c.execute("INSERT INTO officials (role, name) VALUES (?,?)", (o["role"], o["name"]))

    # --- players ---
    c.execute("DROP TABLE IF EXISTS players")
    c.execute("""
        CREATE TABLE players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team TEXT NOT NULL, license_number TEXT, name TEXT NOT NULL,
            jersey_number INTEGER, role TEXT NOT NULL DEFAULT 'player',
            starter INTEGER NOT NULL DEFAULT 0, entry_quarter INTEGER
        )
    """)
    for p in players:
        c.execute("INSERT INTO players (team, license_number, name, jersey_number, role, starter, entry_quarter) VALUES (?,?,?,?,?,?,?)",
                  (p["team"], p["license_number"], p["name"], p["jersey_number"],
                   p["role"], p["starter"], p["entry_quarter"]))

    # --- personal_fouls ---
    c.execute("DROP TABLE IF EXISTS personal_fouls")
    c.execute("""
        CREATE TABLE personal_fouls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team TEXT NOT NULL, jersey_number INTEGER,
            foul_number INTEGER NOT NULL, minute TEXT,
            quarter INTEGER NOT NULL,
            foul_type TEXT NOT NULL DEFAULT 'defensive',
            foul_category TEXT,
            free_throws INTEGER,
            offsetting INTEGER NOT NULL DEFAULT 0
        )
    """)
    for f in personal_fouls:
        c.execute("""INSERT INTO personal_fouls
                     (team, jersey_number, foul_number, minute, quarter,
                      foul_type, foul_category, free_throws, offsetting)
                     VALUES (?,?,?,?,?,?,?,?,?)""",
                  (f["team"], f["jersey_number"], f["foul_number"], f["minute"], f["quarter"],
                   f["foul_type"], f.get("foul_category"), f.get("free_throws"),
                   f.get("offsetting", 0)))

    # --- team_fouls ---
    c.execute("DROP TABLE IF EXISTS team_fouls")
    c.execute("""
        CREATE TABLE team_fouls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team TEXT NOT NULL, quarter INTEGER NOT NULL,
            foul_count INTEGER NOT NULL
        )
    """)
    for f in team_fouls:
        c.execute("INSERT INTO team_fouls (team, quarter, foul_count) VALUES (?,?,?)",
                  (f["team"], f["quarter"], f["foul_count"]))

    # --- timeouts ---
    c.execute("DROP TABLE IF EXISTS timeouts")
    c.execute("""
        CREATE TABLE timeouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team TEXT NOT NULL, quarter INTEGER NOT NULL,
            minute TEXT NOT NULL
        )
    """)
    for t in timeouts:
        c.execute("INSERT INTO timeouts (team, quarter, minute) VALUES (?,?,?)",
                  (t["team"], t["quarter"], t["minute"]))

    # --- quarter_scores ---
    c.execute("DROP TABLE IF EXISTS quarter_scores")
    c.execute("""
        CREATE TABLE quarter_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quarter TEXT NOT NULL, score_a INTEGER, score_b INTEGER
        )
    """)
    for q in quarter_scores:
        c.execute("INSERT INTO quarter_scores (quarter, score_a, score_b) VALUES (?,?,?)",
                  (q["quarter"], q["score_a"], q["score_b"]))

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Extracting scoresheet data...")
    all_chars, all_circles = extract_all_from_pdf(PDF_PATH)

    # Running score
    rs_records = extract_running_score(all_chars, all_circles)

    # Match info
    match_info = extract_match_info(all_chars)

    # Referees & Officials
    referees = extract_referees(all_chars)
    officials = extract_officials(all_chars)

    # Quarter scores
    quarter_scores = extract_quarter_scores(all_chars)

    # Players
    players_a = extract_players(all_chars, all_circles, "A", TEAM_A_PLAYERS, TEAM_A_COACH)
    players_b = extract_players(all_chars, all_circles, "B", TEAM_B_PLAYERS, TEAM_B_COACH)
    all_players = players_a + players_b

    # Personal fouls (including coach technical fouls)
    fouls_a = extract_personal_fouls(all_chars, all_circles, "A", TEAM_A_PLAYERS, FOUL_SLOTS_A, all_players, TEAM_A_COACH)
    fouls_b = extract_personal_fouls(all_chars, all_circles, "B", TEAM_B_PLAYERS, FOUL_SLOTS_B, all_players, TEAM_B_COACH)
    all_personal_fouls = fouls_a + fouls_b

    # Team fouls
    team_fouls_a = extract_team_fouls(all_chars, "A")
    team_fouls_b = extract_team_fouls(all_chars, "B")
    all_team_fouls = team_fouls_a + team_fouls_b

    # Timeouts
    timeouts_a = extract_timeouts(all_chars, "A")
    timeouts_b = extract_timeouts(all_chars, "B")
    all_timeouts = timeouts_a + timeouts_b

    # Write everything
    write_db(DB_PATH, rs_records, match_info, referees, officials,
             all_players, all_personal_fouls, all_team_fouls, all_timeouts, quarter_scores)

    # --- Summary ---
    print(f"\n→ {DB_PATH}")
    print(f"\nrunning_score: {len(rs_records)} records")

    print(f"\nmatch_info:")
    print(f"  {match_info['team_a']} vs {match_info['team_b']}")
    print(f"  {match_info['venue']}, {match_info['match_date']} {match_info['match_time']}")
    print(f"  Végeredmény: {match_info['score_a']} - {match_info['score_b']}")

    print(f"\nreferees: {len(referees)}")
    for r in referees:
        print(f"  {r['role']}: {r['name']}")

    print(f"\nofficials: {len(officials)}")
    for o in officials:
        print(f"  {o['role']}: {o['name']}")

    print(f"\nplayers: {len(all_players)} ({len(players_a)} A + {len(players_b)} B)")
    for p in all_players:
        starter_mark = "★" if p["starter"] else " "
        q = f"Q{p['entry_quarter']}" if p["entry_quarter"] else "  "
        role = f"({p['role']})" if p["role"] != "player" else ""
        print(f"  {p['team']} {starter_mark} #{str(p['jersey_number'] or '-'):>2s} {q} {p['name']} {role}")

    print(f"\npersonal_fouls: {len(all_personal_fouls)}")
    print(f"  A: {len(fouls_a)}, B: {len(fouls_b)}")

    print(f"\nteam_fouls:")
    for f in all_team_fouls:
        print(f"  {f['team']} Q{f['quarter']}: {f['foul_count']}")

    print(f"\ntimeouts: {len(all_timeouts)}")
    for t in all_timeouts:
        print(f"  {t['team']} Q{t['quarter']}: {t['minute']}. perc")

    print(f"\nquarter_scores:")
    for q in quarter_scores:
        print(f"  {q['quarter']}. negyed: A {q['score_a']} - B {q['score_b']}")
