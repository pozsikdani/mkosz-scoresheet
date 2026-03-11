#!/usr/bin/env python3
"""
Extract all structured data from MKOSZ basketball scoresheet PDFs
into a SQLite database.

Supports single-file and batch (directory) processing.

Tables: matches, referees, officials, players, personal_fouls,
        team_fouls, timeouts, quarter_scores, running_score,
        scoring_events, player_game_stats, extraction_log
"""

import fitz  # PyMuPDF
import sqlite3
import os
import re
import glob
import time
import json
import argparse
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PDF_PATH = os.path.join(SCRIPT_DIR, "hun3k_125657.pdf")
DEFAULT_DB_PATH = os.path.join(SCRIPT_DIR, "season.sqlite")

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

# Column boundaries for the running score table.
# Boundaries shifted left by 2px from nominal grid lines to better capture
# characters that sit near column edges (improves Második félidő accuracy).
# Additionally, M*/B*-1 boundaries (4th value in each group) are shifted
# left by an extra 2px (total -4px) because some PDFs position the tens
# digit of B-team jersey numbers slightly left of the B*-1 column.
COL_BOUNDS = [
    # Első félidő — 1. oszlopcsoport (A1-1, A1-2, M1, B1-1, B1-2)
    479, 501, 522, 539, 562,
    # Első félidő — 2. oszlopcsoport (A2-1, A2-2, M2, B2-1, B2-2)
    584, 603, 625, 642, 663,
    # Második félidő — 1. oszlopcsoport
    685, 706, 727, 745, 767,
    # Második félidő — 2. oszlopcsoport
    790, 809, 830, 847, 868,
    # Hosszabbítás — 1. oszlopcsoport
    889, 910, 931, 949, 971,
    # Hosszabbítás — 2. oszlopcsoport
    992, 1012, 1033, 1051, 1074,
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


def extract_running_score(all_chars, all_circles, template=None):
    """Extract the Folyamatos Eredmény table.

    Each cell (row × column) produces exactly ONE record — all characters
    within the cell are concatenated (no gap-based token splitting).
    The y-filter is tightened to exclude text below the grid (e.g. "Eredmény:").
    """
    if template is None:
        template = detect_template(all_chars)
    off = template["off_body"]
    row_top = ROW_TOP + off

    # y upper bound: row 42 bottom = row_top + NUM_ROWS * ROW_HEIGHT
    y_max = row_top + NUM_ROWS * ROW_HEIGHT + 2  # small margin
    y_min = row_top - 8
    raw_chars = [ch for ch in all_chars if ch["x"] >= 480 and y_min < ch["y"] < y_max]
    rs_circles = [(x0, y0, x1, y1) for x0, y0, x1, y1 in all_circles
                  if x0 >= 475 and y0 >= y_min - 10 and y1 <= y_max + 5]

    def _get_row_local(y):
        r = int((y - row_top) / ROW_HEIGHT) + 1
        return max(1, min(r, NUM_ROWS))

    cells = {}
    for ch in raw_chars:
        col_info = _get_column(ch["x"])
        if col_info is None:
            continue
        header, cname = col_info
        row = _get_row_local(ch["y"])
        key = (row, header, cname)
        cells.setdefault(key, []).append((ch["x"], ch["c"], ch["color"]))

    # --- Boundary correction pass ---
    # At column-group boundaries, characters can "spill" between adjacent
    # columns due to slight x-position variations across PDFs.  Two cases:
    #
    #  1) B*-2 (last col of group) picks up chars from the next group's
    #     A*-1 — detected as chars far from the column's left boundary
    #     or separated from the main cluster by a large x-gap.
    #
    #  2) A*-1 (first col of group) picks up chars that really belong to
    #     the A*-2 column next to it — detected as chars near the *-1/*-2
    #     boundary with a large x-gap from the jersey cluster.
    #
    # In both cases, we re-assign or drop the stray characters.

    _col_left_map = {}
    _col_right_map = {}
    for left, right, h, cn in COLUMNS:
        _col_left_map[(h, cn)] = left
        _col_right_map[(h, cn)] = right

    # Identify the *-2 column key for each *-1 column (same header & group)
    _jersey_to_score = {}   # (h, "*-1") → (h, "*-2")
    for left, right, h, cn in COLUMNS:
        if cn.endswith("-1"):
            score_cn = cn[:-1] + "2"  # A1-1 → A1-2, B1-1 → B1-2, etc.
            _jersey_to_score[(h, cn)] = (h, score_cn)

    # Build mapping: B*-2 → next group's A*-1 for cross-group re-assignment.
    # COLUMNS order: A1-1, A1-2, M1, B1-1, B1-2, A2-1, A2-2, ...
    _b2_to_next_a1 = {}
    for ci in range(len(COLUMNS) - 1):
        _, _, h, cn = COLUMNS[ci]
        if cn == "B1-2" or cn == "B2-2":
            next_left, next_right, nh, ncn = COLUMNS[ci + 1]
            if ncn.startswith("A"):
                _b2_to_next_a1[(h, cn)] = (nh, ncn)

    # Case 1: B*-2 columns — re-assign stray right-side chars to next A*-1
    for key in list(cells.keys()):
        row, header, cname = key
        if cname != "B1-2" and cname != "B2-2":
            continue
        char_list = cells[key]
        if not char_list:
            continue
        char_list.sort(key=lambda t: t[0])

        col_left = _col_left_map.get((header, cname), 0)
        next_a1 = _b2_to_next_a1.get((header, cname))

        # If ALL chars are far from the left boundary → entirely stray,
        # re-assign them to the next group's A*-1 column.
        if char_list[0][0] - col_left > 15:
            if next_a1:
                a1_key = (row, next_a1[0], next_a1[1])
                cells.setdefault(a1_key, [])
                cells[a1_key] = char_list + cells[a1_key]
            del cells[key]
            continue

        # If there's a large gap, keep only the left cluster;
        # re-assign right-side chars to next A*-1.
        if len(char_list) > 1:
            filtered = [char_list[0]]
            spill_chars = []
            for i in range(1, len(char_list)):
                gap = char_list[i][0] - char_list[i - 1][0]
                if gap > 10:
                    spill_chars = char_list[i:]
                    break
                filtered.append(char_list[i])
            cells[key] = filtered
            if spill_chars and next_a1:
                a1_key = (row, next_a1[0], next_a1[1])
                cells.setdefault(a1_key, [])
                cells[a1_key] = spill_chars + cells[a1_key]

    # Case 2: *-1 (jersey) columns — spill right-side chars to *-2 (score)
    for key in list(cells.keys()):
        row, header, cname = key
        if not cname.endswith("-1"):
            continue
        char_list = cells[key]
        if len(char_list) < 2:
            continue
        char_list.sort(key=lambda t: t[0])

        col_right = _col_right_map.get((header, cname), 9999)

        # Find the largest internal gap
        max_gap = 0
        split_at = -1
        for i in range(1, len(char_list)):
            gap = char_list[i][0] - char_list[i - 1][0]
            if gap > max_gap:
                max_gap = gap
                split_at = i

        # If there's a significant gap AND the right-side chars are near
        # the column boundary, they likely belong to the *-2 column.
        if max_gap > 10 and split_at > 0:
            right_chars = char_list[split_at:]
            # Check: are the right-side chars within 5px of the boundary?
            if right_chars[0][0] >= col_right - 5:
                # Move them to the adjacent *-2 column
                score_key_info = _jersey_to_score.get((header, cname))
                if score_key_info:
                    score_key = (row, score_key_info[0], score_key_info[1])
                    cells.setdefault(score_key, [])
                    cells[score_key] = right_chars + cells[score_key]
                cells[key] = char_list[:split_at]

    records = []
    for (row, header, cname), char_list in sorted(cells.items()):
        char_list.sort(key=lambda t: t[0])

        # All characters in one cell form ONE token (no gap-based splitting).
        token_chars = char_list
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

def detect_template(all_chars):
    """Detect PDF template type based on match_id vertical position.

    Returns a y-offset dict:
        TYPE1 (match_id F at y≈178): offset_header=0, offset_body=0
        TYPE2 (match_id F at y≈168): offset_header=-10, offset_body=-20

    The offset values describe how much TYPE2 coordinates are shifted UP
    relative to TYPE1 (i.e. TYPE2_y = TYPE1_y + offset).
    """
    f_chars = [ch for ch in all_chars
               if ch["c"] == "F" and ch["x"] < 40 and 150 < ch["y"] < 200]
    if f_chars and f_chars[0]["y"] < 173:
        # TYPE2
        return {"name": "TYPE2", "off_id": -10, "off_body": -20}
    return {"name": "TYPE1", "off_id": 0, "off_body": 0}


def extract_match_info(all_chars, template=None):
    """Extract match metadata from header and footer."""
    if template is None:
        template = detect_template(all_chars)
    off_id = template["off_id"]
    off = template["off_body"]

    def blue_text(x_min, x_max, y_min, y_max, gap=2.0):
        chars = collect_chars_in_rect(all_chars, x_min, x_max, y_min, y_max,
                                      color_filter=OFFICIAL_BLUE)
        return assemble_text(chars, gap_threshold=gap)

    # Team names — y≈83-95 (same for both templates)
    team_a = blue_text(90, 600, 80, 100)
    team_b = blue_text(600, 900, 80, 100)

    # Venue — y≈126-136 (same for both templates)
    venue = blue_text(200, 500, 123, 140)

    # Match ID — TYPE1: y≈175-185, TYPE2: y≈165-175
    match_id = blue_text(20, 200, 172 + off_id, 190 + off_id)

    # Date and time — TYPE1: y≈205-215, TYPE2: y≈185-195
    match_date = blue_text(200, 360, 202 + off, 220 + off)
    match_time = blue_text(360, 450, 202 + off, 220 + off)

    # Final score — TYPE1: y≈1548-1565, TYPE2: y≈1528-1545
    score_chars_a = collect_chars_in_rect(all_chars, 698, 730, 1548 + off, 1565 + off)
    score_a_text = assemble_number([c for c in score_chars_a if c["c"].isdigit()])

    score_chars_b = collect_chars_in_rect(all_chars, 908, 935, 1548 + off, 1565 + off)
    score_b_text = assemble_number([c for c in score_chars_b if c["c"].isdigit()])

    # Winner — TYPE1: y≈1575-1590, TYPE2: y≈1555-1570
    winner = blue_text(650, 900, 1572 + off, 1595 + off)

    # Closure timestamp — TYPE1: y≈1620-1635, TYPE2: y≈1600-1615
    closure = blue_text(900, 1080, 1618 + off, 1640 + off)

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

def extract_officials(all_chars, template=None):
    """Extract officials (scorer, timekeeper, etc.) from the footer."""
    if template is None:
        template = detect_template(all_chars)
    off = template["off_body"]

    officials = []
    roles = [
        ("Jegyző",           1414 + off, 1435 + off),
        ("Időmérő",          1462 + off, 1480 + off),
        ("24\"-es időmérő",  1488 + off, 1505 + off),
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

def extract_quarter_scores(all_chars, template=None):
    """Extract quarter-by-quarter scores from the footer."""
    if template is None:
        template = detect_template(all_chars)
    off = template["off_body"]

    scores = []
    quarter_rows = [
        ("1", 1413 + off, 1430 + off),
        ("2", 1438 + off, 1455 + off),
        ("3", 1463 + off, 1480 + off),
        ("4", 1488 + off, 1505 + off),
        ("Hosszabbítás", 1513 + off, 1530 + off),
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

# Player roster y-ranges — TYPE1 defaults (first row top, last row bottom, row height)
TEAM_A_PLAYERS = {"y_start": 430, "y_end": 725, "row_height": 24.5, "max_rows": 12}
TEAM_B_PLAYERS = {"y_start": 1033, "y_end": 1220, "row_height": 24.5, "max_rows": 12}

# Coach y-ranges — TYPE1 defaults
TEAM_A_COACH = {"coach_y": (730, 760), "asst_y": (768, 795)}
TEAM_B_COACH = {"coach_y": (1330, 1360), "asst_y": (1358, 1385)}


def _offset_player_region(region, off):
    """Apply y-offset to a player region dict."""
    return {
        "y_start": region["y_start"] + off,
        "y_end": region["y_end"] + off,
        "row_height": region["row_height"],
        "max_rows": region["max_rows"],
    }


def _offset_coach_region(region, off):
    """Apply y-offset to a coach region dict."""
    return {
        "coach_y": (region["coach_y"][0] + off, region["coach_y"][1] + off),
        "asst_y": (region["asst_y"][0] + off, region["asst_y"][1] + off),
    }


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
        # Long names can wrap to a second line in the PDF, and the wrapped
        # portion may spill into the NEXT row's y-band (within ~2px of the
        # top).  To avoid garbling, we group chars by y-line and drop any
        # line that sits within 8px of the row's top edge when there are
        # other, lower lines present (those are the actual name for this row).
        name_chars = collect_chars_in_rect(all_chars, 95, 275, y_min, y_max,
                                            color_filter=OFFICIAL_BLUE)
        # Player names never contain digits.  In some PDFs the first digit
        # of the jersey number sits at x≈274 which falls inside the name
        # rect (95-275), causing a trailing stray digit.  Filter them out.
        name_chars = [c for c in name_chars if not c["c"].isdigit()]
        if name_chars:
            # Group by y-line (tolerance 5px)
            name_chars_sorted = sorted(name_chars, key=lambda c: c["y"])
            y_lines = []
            cur_line = [name_chars_sorted[0]]
            for i in range(1, len(name_chars_sorted)):
                if name_chars_sorted[i]["y"] - cur_line[0]["y"] > 5:
                    y_lines.append(cur_line)
                    cur_line = [name_chars_sorted[i]]
                else:
                    cur_line.append(name_chars_sorted[i])
            y_lines.append(cur_line)

            if len(y_lines) > 1:
                # Drop lines whose y is within 8px of the row top (overflow
                # from previous row's wrapped name).
                kept = [ln for ln in y_lines if ln[0]["y"] - y_min >= 8]
                if kept:
                    y_lines = kept

                # Assemble each y-line separately to avoid interleaving
                # characters from wrapped names (e.g. "SCHWARCZENBERGER"
                # wrapping within its own cell → two overlapping x-ranges).
                name = " ".join(
                    assemble_text(ln, gap_threshold=2.0) for ln in y_lines
                )
            else:
                name = assemble_text(name_chars, gap_threshold=2.0)
        else:
            name = ""

        # Jersey number — x 265-330, blue
        # Some PDFs position the tens digit of 2-digit jerseys as far left
        # as x≈270, so we start at 265 to capture them reliably.
        jersey_chars = collect_chars_in_rect(all_chars, 265, 330, y_min, y_max,
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


def extract_team_fouls(all_chars, team, template=None):
    """Extract team foul counts per quarter."""
    if template is None:
        template = detect_template(all_chars)
    off = template["off_body"]

    fouls = []
    for row_cfg in TEAM_FOUL_REGIONS[team]["rows"]:
        y_min, y_max = row_cfg["y_min"] + off, row_cfg["y_max"] + off

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


def extract_timeouts(all_chars, team, template=None):
    """Extract timeout events (minute + quarter from color)."""
    if template is None:
        template = detect_template(all_chars)
    off = template["off_body"]

    timeouts = []

    for row_cfg in TIMEOUT_REGIONS[team]["rows"]:
        y_min, y_max = row_cfg["y_min"] + off, row_cfg["y_max"] + off
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
# Database schema + insert functions (multi-match)
# ---------------------------------------------------------------------------

def create_schema(conn):
    """Create all tables if they don't exist. Supports multi-match storage."""
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id        TEXT PRIMARY KEY,
            team_a          TEXT NOT NULL,
            team_b          TEXT NOT NULL,
            venue           TEXT,
            match_date      TEXT NOT NULL,
            match_time      TEXT,
            score_a         INTEGER,
            score_b         INTEGER,
            winner          TEXT,
            closure_timestamp TEXT,
            source_pdf      TEXT,
            extracted_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS referees (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id  TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            role      TEXT NOT NULL,
            name      TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS officials (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id  TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            role      TEXT NOT NULL,
            name      TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            team            TEXT NOT NULL CHECK (team IN ('A', 'B')),
            license_number  TEXT,
            name            TEXT NOT NULL,
            jersey_number   INTEGER,
            role            TEXT NOT NULL DEFAULT 'player',
            starter         INTEGER NOT NULL DEFAULT 0,
            entry_quarter   INTEGER,
            UNIQUE(match_id, team, license_number)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS personal_fouls (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            team            TEXT NOT NULL CHECK (team IN ('A', 'B')),
            jersey_number   INTEGER,
            foul_number     INTEGER NOT NULL,
            minute          TEXT,
            quarter         INTEGER NOT NULL,
            foul_type       TEXT NOT NULL DEFAULT 'defensive',
            foul_category   TEXT,
            free_throws     INTEGER,
            offsetting      INTEGER NOT NULL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS team_fouls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id    TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            team        TEXT NOT NULL CHECK (team IN ('A', 'B')),
            quarter     INTEGER NOT NULL,
            foul_count  INTEGER NOT NULL,
            UNIQUE(match_id, team, quarter)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS timeouts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id  TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            team      TEXT NOT NULL CHECK (team IN ('A', 'B')),
            quarter   INTEGER NOT NULL,
            minute    TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS quarter_scores (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id  TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            quarter   TEXT NOT NULL,
            score_a   INTEGER,
            score_b   INTEGER,
            UNIQUE(match_id, quarter)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS running_score (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id    TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            header      TEXT NOT NULL,
            column_name TEXT NOT NULL,
            color       TEXT NOT NULL,
            circled     INTEGER NOT NULL DEFAULT 0,
            row_number  INTEGER NOT NULL,
            character   TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scoring_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            event_seq       INTEGER NOT NULL,
            quarter         INTEGER NOT NULL,
            minute          TEXT,
            team            TEXT NOT NULL CHECK (team IN ('A', 'B')),
            jersey_number   INTEGER NOT NULL,
            license_number  TEXT,
            points          INTEGER NOT NULL CHECK (points >= 0),
            shot_type       TEXT NOT NULL CHECK (shot_type IN ('2FG', '3FG', 'FT', 'MULTI')),
            made            INTEGER NOT NULL CHECK (made IN (0, 1)),
            score_a         INTEGER NOT NULL,
            score_b         INTEGER NOT NULL,
            UNIQUE(match_id, event_seq)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS player_game_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
            team            TEXT NOT NULL CHECK (team IN ('A', 'B')),
            jersey_number   INTEGER NOT NULL,
            license_number  TEXT,
            name            TEXT NOT NULL,
            points          INTEGER NOT NULL DEFAULT 0,
            fg2_made        INTEGER NOT NULL DEFAULT 0,
            fg3_made        INTEGER NOT NULL DEFAULT 0,
            ft_made         INTEGER NOT NULL DEFAULT 0,
            ft_attempted    INTEGER NOT NULL DEFAULT 0,
            personal_fouls  INTEGER NOT NULL DEFAULT 0,
            starter         INTEGER NOT NULL DEFAULT 0,
            entry_quarter   INTEGER,
            UNIQUE(match_id, team, jersey_number)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS extraction_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id        TEXT,
            source_pdf      TEXT NOT NULL,
            extracted_at    TEXT NOT NULL DEFAULT (datetime('now')),
            status          TEXT NOT NULL CHECK (status IN ('success', 'error', 'skipped')),
            error_message   TEXT,
            duration_ms     INTEGER,
            record_counts   TEXT
        )
    """)

    # Indexes for common queries
    for stmt in [
        "CREATE INDEX IF NOT EXISTS idx_referees_match ON referees(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_officials_match ON officials(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_players_match ON players(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_players_license ON players(license_number)",
        "CREATE INDEX IF NOT EXISTS idx_pf_match ON personal_fouls(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_rs_match ON running_score(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_se_match ON scoring_events(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_se_license ON scoring_events(license_number)",
        "CREATE INDEX IF NOT EXISTS idx_pgs_match ON player_game_stats(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_pgs_license ON player_game_stats(license_number)",
    ]:
        c.execute(stmt)

    conn.commit()


def delete_match(conn, match_id):
    """Delete all data for a match (ON DELETE CASCADE handles child rows)."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))


def insert_match(conn, match_info, source_pdf=None):
    """Insert into matches table."""
    m = match_info
    conn.execute("""
        INSERT INTO matches (match_id, team_a, team_b, venue, match_date, match_time,
                             score_a, score_b, winner, closure_timestamp, source_pdf)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (m["match_id"], m["team_a"], m["team_b"], m["venue"], m["match_date"],
          m["match_time"], m["score_a"], m["score_b"], m["winner"],
          m["closure_timestamp"], source_pdf))


def insert_referees(conn, match_id, referees):
    for r in referees:
        conn.execute("INSERT INTO referees (match_id, role, name) VALUES (?,?,?)",
                     (match_id, r["role"], r["name"]))


def insert_officials(conn, match_id, officials):
    for o in officials:
        conn.execute("INSERT INTO officials (match_id, role, name) VALUES (?,?,?)",
                     (match_id, o["role"], o["name"]))


def insert_players(conn, match_id, players):
    for p in players:
        conn.execute("""
            INSERT OR IGNORE INTO players (match_id, team, license_number, name, jersey_number,
                                 role, starter, entry_quarter)
            VALUES (?,?,?,?,?,?,?,?)
        """, (match_id, p["team"], p["license_number"], p["name"],
              p["jersey_number"], p["role"], p["starter"], p["entry_quarter"]))


def insert_personal_fouls(conn, match_id, fouls):
    for f in fouls:
        conn.execute("""
            INSERT INTO personal_fouls (match_id, team, jersey_number, foul_number,
                                        minute, quarter, foul_type, foul_category,
                                        free_throws, offsetting)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (match_id, f["team"], f["jersey_number"], f["foul_number"],
              f["minute"], f["quarter"], f["foul_type"], f.get("foul_category"),
              f.get("free_throws"), f.get("offsetting", 0)))


def insert_team_fouls(conn, match_id, team_fouls):
    for f in team_fouls:
        conn.execute("INSERT INTO team_fouls (match_id, team, quarter, foul_count) VALUES (?,?,?,?)",
                     (match_id, f["team"], f["quarter"], f["foul_count"]))


def insert_timeouts(conn, match_id, timeouts):
    for t in timeouts:
        conn.execute("INSERT INTO timeouts (match_id, team, quarter, minute) VALUES (?,?,?,?)",
                     (match_id, t["team"], t["quarter"], t["minute"]))


def insert_quarter_scores(conn, match_id, quarter_scores):
    for q in quarter_scores:
        conn.execute("INSERT INTO quarter_scores (match_id, quarter, score_a, score_b) VALUES (?,?,?,?)",
                     (match_id, q["quarter"], q["score_a"], q["score_b"]))


def insert_running_score(conn, match_id, rs_records):
    for r in rs_records:
        conn.execute("""
            INSERT INTO running_score (match_id, header, column_name, color, circled,
                                       row_number, character)
            VALUES (?,?,?,?,?,?,?)
        """, (match_id, r["header"], r["column"], r["color"], r["circled"],
              r["row_number"], r["character"]))


# ---------------------------------------------------------------------------
# Scoring events computation (running_score → structured events)
# ---------------------------------------------------------------------------

# Color → quarter mapping for scoring events
SCORING_COLOR_QUARTER = {
    "red": 1,
    "black": 2,
    "green": 3,
    "blue": 4,
}


def compute_scoring_events(rs_records, players_list, match_id):
    """Transform raw running_score records into structured scoring events.

    Each event = one shot attempt (made basket or missed FT).

    Rules:
    - Score "-" = missed free throw (points=0, made=0)
    - No jersey number = continuation FT (same player as previous)
    - Circled jersey = three-pointer
    - Points = delta of cumulative score
    - Quarter determined by color (red=Q1, black=Q2, green=Q3, blue=Q4)
    """
    # Build player lookup: (team, jersey_str) → license_number
    player_lookup = {}
    for p in players_list:
        if p["jersey_number"] is not None:
            key = (p["team"], str(p["jersey_number"]))
            player_lookup[key] = p.get("license_number")

    # Organize running_score into rows by (header, group, row_number)
    # header order: Első félidő=0, Második félidő=1, Hosszabbítás=2
    HEADER_ORDER = {"Első félidő": 0, "Második félidő": 1, "Hosszabbítás": 2}

    # Group records by (header, column_name, row_number)
    cells = {}
    for r in rs_records:
        key = (r["header"], r["column"], r["row_number"])
        cells[key] = r

    # Build flat event timeline: iterate G1 then G2 for each period
    timeline = []
    for header in ["Első félidő", "Második félidő", "Hosszabbítás"]:
        for group in [1, 2]:
            ja_col = f"A{group}-1"
            sa_col = f"A{group}-2"
            m_col = f"M{group}"
            jb_col = f"B{group}-1"
            sb_col = f"B{group}-2"

            for rn in range(1, NUM_ROWS + 1):
                ja = cells.get((header, ja_col, rn))
                sa = cells.get((header, sa_col, rn))
                mn = cells.get((header, m_col, rn))
                jb = cells.get((header, jb_col, rn))
                sb = cells.get((header, sb_col, rn))

                if any(x is not None for x in [ja, sa, mn, jb, sb]):
                    timeline.append({
                        "ja": ja, "sa": sa, "minute": mn,
                        "jb": jb, "sb": sb, "header": header,
                    })

    # Walk through timeline, computing events
    events = []
    score_a, score_b = 0, 0
    last_jersey_a, last_jersey_b = None, None
    seq = 0

    for row in timeline:
        ja, sa, mn, jb, sb = row["ja"], row["sa"], row["minute"], row["jb"], row["sb"]
        minute_str = mn["character"] if mn else None

        # --- Team A event ---
        if sa is not None:
            score_val = sa["character"]
            score_circled = sa["circled"]
            jersey_val = ja["character"] if ja else None
            jersey_circled = ja["circled"] if ja else 0
            color = sa["color"]

            if jersey_val and jersey_val != "-" and jersey_val.isdigit():
                last_jersey_a = jersey_val
            jersey = last_jersey_a

            if jersey and jersey.isdigit():
                quarter = SCORING_COLOR_QUARTER.get(color, None)
                if score_val == "-":
                    # Missed FT
                    seq += 1
                    events.append({
                        "match_id": match_id, "event_seq": seq,
                        "quarter": quarter, "minute": minute_str,
                        "team": "A", "jersey_number": int(jersey),
                        "license_number": player_lookup.get(("A", jersey)),
                        "points": 0, "shot_type": "FT", "made": 0,
                        "score_a": score_a, "score_b": score_b,
                    })
                else:
                    try:
                        new_score = int(score_val)
                    except ValueError:
                        pass  # Non-numeric score (e.g. text bleed), skip
                    else:
                        pts = new_score - score_a

                        if pts == 0:
                            score_a = new_score  # Reference entry, skip
                        elif pts < 0 or pts > 10:
                            pass  # Backwards or huge gap → likely garbage, DON'T update accumulator
                        else:
                            score_a = new_score
                            if pts == 3 or (jersey_circled and pts > 0):
                                shot_type = "3FG"
                            elif pts == 1:
                                shot_type = "FT"
                            elif pts == 2:
                                shot_type = "2FG"
                            else:
                                shot_type = "MULTI"  # 4-10 pts: aggregated events

                            seq += 1
                            events.append({
                                "match_id": match_id, "event_seq": seq,
                                "quarter": quarter, "minute": minute_str,
                                "team": "A", "jersey_number": int(jersey),
                                "license_number": player_lookup.get(("A", jersey)),
                                "points": pts, "shot_type": shot_type, "made": 1,
                                "score_a": score_a, "score_b": score_b,
                            })

        # --- Team B event ---
        if sb is not None:
            score_val = sb["character"]
            score_circled = sb["circled"]
            jersey_val = jb["character"] if jb else None
            jersey_circled = jb["circled"] if jb else 0
            color = sb["color"]

            if jersey_val and jersey_val != "-" and jersey_val.isdigit():
                last_jersey_b = jersey_val
            jersey = last_jersey_b

            if jersey and jersey.isdigit():
                quarter = SCORING_COLOR_QUARTER.get(color, None)
                if score_val == "-":
                    seq += 1
                    events.append({
                        "match_id": match_id, "event_seq": seq,
                        "quarter": quarter, "minute": minute_str if sa is None else None,
                        "team": "B", "jersey_number": int(jersey),
                        "license_number": player_lookup.get(("B", jersey)),
                        "points": 0, "shot_type": "FT", "made": 0,
                        "score_a": score_a, "score_b": score_b,
                    })
                else:
                    try:
                        new_score = int(score_val)
                    except ValueError:
                        pass  # Non-numeric score, skip
                    else:
                        pts = new_score - score_b

                        if pts == 0:
                            score_b = new_score  # Reference entry, skip
                        elif pts < 0 or pts > 10:
                            pass  # Backwards or huge gap → likely garbage, DON'T update accumulator
                        else:
                            score_b = new_score
                            if pts == 3 or (jersey_circled and pts > 0):
                                shot_type = "3FG"
                            elif pts == 1:
                                shot_type = "FT"
                            elif pts == 2:
                                shot_type = "2FG"
                            else:
                                shot_type = "MULTI"

                            seq += 1
                            events.append({
                                "match_id": match_id, "event_seq": seq,
                                "quarter": quarter, "minute": minute_str if sa is None else None,
                                "team": "B", "jersey_number": int(jersey),
                                "license_number": player_lookup.get(("B", jersey)),
                                "points": pts, "shot_type": shot_type, "made": 1,
                                "score_a": score_a, "score_b": score_b,
                            })

    return events


def insert_scoring_events(conn, events):
    """Insert computed scoring events into the database."""
    for e in events:
        conn.execute("""
            INSERT INTO scoring_events (match_id, event_seq, quarter, minute, team,
                                        jersey_number, license_number, points,
                                        shot_type, made, score_a, score_b)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (e["match_id"], e["event_seq"], e["quarter"], e["minute"],
              e["team"], e["jersey_number"], e["license_number"],
              e["points"], e["shot_type"], e["made"],
              e["score_a"], e["score_b"]))


# ---------------------------------------------------------------------------
# Jersey reconciliation
# ---------------------------------------------------------------------------

def reconcile_jersey_numbers(conn, match_id):
    """Fix truncated jersey numbers in scoring_events.

    When a character in the running-score grid sits a few pixels outside its
    column boundary, the tens digit of a 2-digit jersey number may be lost
    (e.g. 17 → 7).  This function detects such orphan jersey numbers —
    scoring_events entries whose jersey doesn't match any player in the
    roster — and re-maps them to the correct player by matching trailing
    digits.

    The license_number (MKOSZ igazolásszám) is the true unique player
    identifier — jersey numbers and names are NOT unique across matches.
    When a jersey is remapped, the license_number is also updated so that
    cross-match queries can reliably aggregate by license_number.

    Only unambiguous matches (exactly one candidate) are applied.
    """
    for team in ("A", "B"):
        # Build jersey → license_number lookup from the players roster.
        player_map = {}   # jersey_number → license_number
        for jersey, lic in conn.execute(
            "SELECT jersey_number, license_number FROM players "
            "WHERE match_id=? AND team=? AND role IN ('player','captain') "
            "AND jersey_number IS NOT NULL",
            (match_id, team),
        ).fetchall():
            player_map[jersey] = lic

        if not player_map:
            continue

        orphans = conn.execute(
            "SELECT DISTINCT jersey_number FROM scoring_events "
            "WHERE match_id=? AND team=? AND jersey_number IS NOT NULL",
            (match_id, team),
        ).fetchall()

        for (orphan,) in orphans:
            if orphan in player_map:
                # Jersey matches — just ensure license_number is set.
                lic = player_map[orphan]
                if lic:
                    conn.execute(
                        "UPDATE scoring_events SET license_number=? "
                        "WHERE match_id=? AND team=? AND jersey_number=? "
                        "AND (license_number IS NULL OR license_number != ?)",
                        (lic, match_id, team, orphan, lic),
                    )
                continue

            # Orphan: no matching player.  Find candidates whose jersey
            # ends with the same digit (e.g. orphan=7 → 17, 27, 37 …).
            candidates = [
                pj for pj in player_map
                if pj != orphan and pj % 10 == orphan % 10
            ]

            if len(candidates) == 1:
                correct_jersey = candidates[0]
                correct_lic = player_map[correct_jersey]
                conn.execute(
                    "UPDATE scoring_events "
                    "SET jersey_number=?, license_number=? "
                    "WHERE match_id=? AND team=? AND jersey_number=?",
                    (correct_jersey, correct_lic, match_id, team, orphan),
                )


# ---------------------------------------------------------------------------
# Player game stats computation
# ---------------------------------------------------------------------------

def compute_player_game_stats(conn, match_id):
    """Aggregate scoring_events + personal_fouls into per-player box scores.

    JOINs use license_number (MKOSZ igazolásszám) as the primary key when
    available, falling back to (team, jersey_number) otherwise.  This is
    important because jersey numbers are NOT unique identifiers — the same
    player may wear different numbers in different matches.
    """
    conn.execute("""
        INSERT OR REPLACE INTO player_game_stats
            (match_id, team, jersey_number, license_number, name,
             points, fg2_made, fg3_made, ft_made, ft_attempted,
             personal_fouls, starter, entry_quarter)
        SELECT
            p.match_id,
            p.team,
            p.jersey_number,
            p.license_number,
            p.name,
            COALESCE(s.points, 0),
            COALESCE(s.fg2_made, 0),
            COALESCE(s.fg3_made, 0),
            COALESCE(s.ft_made, 0),
            COALESCE(s.ft_att, 0),
            COALESCE(f.foul_count, 0),
            p.starter,
            p.entry_quarter
        FROM players p
        LEFT JOIN (
            SELECT match_id, team, license_number, jersey_number,
                SUM(points) AS points,
                SUM(CASE WHEN shot_type='2FG' AND made=1 THEN 1 ELSE 0 END) AS fg2_made,
                SUM(CASE WHEN shot_type='3FG' AND made=1 THEN 1 ELSE 0 END) AS fg3_made,
                SUM(CASE WHEN shot_type='FT' AND made=1 THEN 1 ELSE 0 END) AS ft_made,
                SUM(CASE WHEN shot_type='FT' THEN 1 ELSE 0 END) AS ft_att
            FROM scoring_events
            WHERE match_id = ?
            GROUP BY match_id, team,
                     CASE WHEN license_number IS NOT NULL AND license_number != ''
                          THEN license_number ELSE jersey_number END
        ) s ON p.match_id = s.match_id AND p.team = s.team
               AND (
                   (p.license_number IS NOT NULL AND p.license_number != ''
                    AND p.license_number = s.license_number)
                   OR
                   (p.license_number IS NULL OR p.license_number = '')
                    AND p.jersey_number = s.jersey_number
               )
        LEFT JOIN (
            SELECT match_id, team, jersey_number, COUNT(*) AS foul_count
            FROM personal_fouls
            WHERE match_id = ?
            GROUP BY match_id, team, jersey_number
        ) f ON p.match_id = f.match_id AND p.team = f.team
               AND p.jersey_number = f.jersey_number
        WHERE p.match_id = ?
          AND p.role IN ('player', 'captain')
          AND p.jersey_number IS NOT NULL
    """, (match_id, match_id, match_id))


# ---------------------------------------------------------------------------
# Single-PDF processing
# ---------------------------------------------------------------------------

def process_single_pdf(pdf_path, conn):
    """Extract one PDF and insert all data into the multi-match database.

    Returns (match_id, record_counts) on success.
    """
    source_pdf = os.path.basename(pdf_path)

    # 1. Extract raw data from PDF
    all_chars, all_circles = extract_all_from_pdf(pdf_path)

    # 2. Detect template (TYPE1 vs TYPE2 based on y-coordinate layout)
    template = detect_template(all_chars)
    off = template["off_body"]

    # 3. Extract structured data with template-aware coordinates
    match_info = extract_match_info(all_chars, template)
    match_id = match_info["match_id"]

    rs_records = extract_running_score(all_chars, all_circles, template)
    referees = extract_referees(all_chars)
    officials = extract_officials(all_chars, template)
    quarter_scores = extract_quarter_scores(all_chars, template)

    # Apply offset to player/coach regions
    ta_players = _offset_player_region(TEAM_A_PLAYERS, off)
    tb_players = _offset_player_region(TEAM_B_PLAYERS, off)
    ta_coach = _offset_coach_region(TEAM_A_COACH, off)
    tb_coach = _offset_coach_region(TEAM_B_COACH, off)

    players_a = extract_players(all_chars, all_circles, "A", ta_players, ta_coach)
    players_b = extract_players(all_chars, all_circles, "B", tb_players, tb_coach)
    all_players = players_a + players_b

    fouls_a = extract_personal_fouls(all_chars, all_circles, "A", ta_players,
                                      FOUL_SLOTS_A, all_players, ta_coach)
    fouls_b = extract_personal_fouls(all_chars, all_circles, "B", tb_players,
                                      FOUL_SLOTS_B, all_players, tb_coach)
    all_personal_fouls = fouls_a + fouls_b

    team_fouls_a = extract_team_fouls(all_chars, "A", template)
    team_fouls_b = extract_team_fouls(all_chars, "B", template)
    all_team_fouls = team_fouls_a + team_fouls_b

    timeouts_a = extract_timeouts(all_chars, "A", template)
    timeouts_b = extract_timeouts(all_chars, "B", template)
    all_timeouts = timeouts_a + timeouts_b

    # 3. Delete existing data for this match (re-processing)
    delete_match(conn, match_id)

    # 4. Insert all data
    insert_match(conn, match_info, source_pdf=source_pdf)
    insert_referees(conn, match_id, referees)
    insert_officials(conn, match_id, officials)
    insert_players(conn, match_id, all_players)
    insert_personal_fouls(conn, match_id, all_personal_fouls)
    insert_team_fouls(conn, match_id, all_team_fouls)
    insert_timeouts(conn, match_id, all_timeouts)
    insert_quarter_scores(conn, match_id, quarter_scores)
    insert_running_score(conn, match_id, rs_records)

    # 5. Compute and insert scoring events
    scoring_events = compute_scoring_events(rs_records, all_players, match_id)
    insert_scoring_events(conn, scoring_events)

    # 6. Reconcile truncated jersey numbers (e.g. 17→7) before aggregation
    reconcile_jersey_numbers(conn, match_id)

    # 7. Compute and insert player game stats
    compute_player_game_stats(conn, match_id)

    record_counts = {
        "running_score": len(rs_records),
        "scoring_events": len(scoring_events),
        "players": len(all_players),
        "personal_fouls": len(all_personal_fouls),
        "team_fouls": len(all_team_fouls),
        "timeouts": len(all_timeouts),
    }

    return match_id, record_counts


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_directory(pdf_dir, db_path, force=False):
    """Batch process all PDFs in a directory."""
    conn = sqlite3.connect(db_path)
    create_schema(conn)

    pdf_files = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")))
    if not pdf_files:
        print(f"Nincs PDF fájl: {pdf_dir}")
        conn.close()
        return

    print(f"Feldolgozás: {len(pdf_files)} PDF → {db_path}")
    print()

    success_count = 0
    error_count = 0

    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)

        # Check if already processed
        if not force:
            existing = conn.execute(
                "SELECT match_id FROM matches WHERE source_pdf = ?", (filename,)
            ).fetchone()
            if existing:
                print(f"  ⏭  {filename} (már feldolgozva: {existing[0]})")
                conn.execute("""
                    INSERT INTO extraction_log (match_id, source_pdf, status)
                    VALUES (?, ?, 'skipped')
                """, (existing[0], filename))
                conn.commit()
                continue

        start = time.time()
        try:
            match_id, counts = process_single_pdf(pdf_path, conn)
            duration_ms = int((time.time() - start) * 1000)

            conn.execute("""
                INSERT INTO extraction_log (match_id, source_pdf, status, duration_ms, record_counts)
                VALUES (?, ?, 'success', ?, ?)
            """, (match_id, filename, duration_ms, json.dumps(counts)))
            conn.commit()

            score_a = conn.execute("SELECT score_a FROM matches WHERE match_id=?", (match_id,)).fetchone()[0]
            score_b = conn.execute("SELECT score_b FROM matches WHERE match_id=?", (match_id,)).fetchone()[0]
            print(f"  ✓  {filename} → {match_id} ({score_a}-{score_b}) [{duration_ms}ms]")
            success_count += 1

        except Exception as e:
            conn.rollback()
            conn.execute("""
                INSERT INTO extraction_log (source_pdf, status, error_message)
                VALUES (?, 'error', ?)
            """, (filename, str(e)))
            conn.commit()
            print(f"  ✗  {filename} — HIBA: {e}")
            error_count += 1

    # Summary
    print()
    total_matches = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    print(f"Összesen: {total_matches} meccs az adatbázisban")
    print(f"  Sikeres: {success_count}, Hibás: {error_count}, Kihagyott: {len(pdf_files) - success_count - error_count}")
    conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_summary(conn, match_id):
    """Print extraction summary for a single match."""
    m = conn.execute("SELECT * FROM matches WHERE match_id=?", (match_id,)).fetchone()
    if not m:
        return
    # m columns: match_id, team_a, team_b, venue, match_date, match_time,
    #            score_a, score_b, winner, closure_timestamp, source_pdf, extracted_at
    print(f"\n  {m[1]} vs {m[2]}")
    print(f"  {m[3]}, {m[4]} {m[5]}")
    print(f"  Végeredmény: {m[6]} - {m[7]}")

    # Scoring events verification
    se_total_a = conn.execute(
        "SELECT COALESCE(SUM(points),0) FROM scoring_events WHERE match_id=? AND team='A'",
        (match_id,)).fetchone()[0]
    se_total_b = conn.execute(
        "SELECT COALESCE(SUM(points),0) FROM scoring_events WHERE match_id=? AND team='B'",
        (match_id,)).fetchone()[0]
    match_ok = (se_total_a == m[6] and se_total_b == m[7])
    check = "✓" if match_ok else "✗"
    print(f"\n  Scoring events ellenőrzés: {check}")
    print(f"    scoring_events összeg: {se_total_a}-{se_total_b}")
    print(f"    match végeredmény:     {m[6]}-{m[7]}")

    # Player game stats top scorers
    rows = conn.execute("""
        SELECT team, jersey_number, name, points, fg2_made, fg3_made, ft_made, ft_attempted
        FROM player_game_stats WHERE match_id=? ORDER BY points DESC LIMIT 5
    """, (match_id,)).fetchall()
    if rows:
        print(f"\n  Top pontszerzők:")
        for team, jn, name, pts, fg2, fg3, ftm, fta in rows:
            t = "A" if team == "A" else "B"
            ft_str = f"{ftm}/{fta}" if fta > 0 else "–"
            print(f"    [{t}] #{jn} {name}: {pts}p (2PT:{fg2} 3PT:{fg3} BÜ:{ft_str})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MKOSZ jegyzőkönyv PDF → SQLite feldolgozó")
    parser.add_argument("pdf_dir", nargs="?", default=None,
                        help="Könyvtár PDF fájlokkal (batch mód)")
    parser.add_argument("--db", default=None,
                        help="Adatbázis fájl útvonala")
    parser.add_argument("--force", action="store_true",
                        help="Már feldolgozott PDF-ek újrafeldolgozása")
    parser.add_argument("--single", type=str, default=None,
                        help="Egyetlen PDF fájl feldolgozása")
    args = parser.parse_args()

    # Determine mode
    if args.single:
        # Single file mode
        pdf_path = args.single
        db_path = args.db or DEFAULT_DB_PATH
    elif args.pdf_dir:
        # Batch directory mode
        db_path = args.db or os.path.join(args.pdf_dir, "season.sqlite")
        process_directory(args.pdf_dir, db_path, force=args.force)
        exit(0)
    else:
        # Default: process the bundled test PDF
        pdf_path = DEFAULT_PDF_PATH
        db_path = args.db or DEFAULT_DB_PATH

    # Single file processing
    print(f"Feldolgozás: {pdf_path}")
    conn = sqlite3.connect(db_path)
    create_schema(conn)

    start = time.time()
    match_id, counts = process_single_pdf(pdf_path, conn)
    duration_ms = int((time.time() - start) * 1000)

    conn.execute("""
        INSERT INTO extraction_log (match_id, source_pdf, status, duration_ms, record_counts)
        VALUES (?, ?, 'success', ?, ?)
    """, (match_id, os.path.basename(pdf_path), duration_ms, json.dumps(counts)))
    conn.commit()

    print(f"\n→ {db_path} ({duration_ms}ms)")
    print(f"  match_id: {match_id}")
    for table, count in counts.items():
        print(f"  {table}: {count}")

    print_summary(conn, match_id)
    conn.close()
