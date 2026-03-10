#!/usr/bin/env python3
"""
Extract the "Folyamatos Eredmény" (Running Score) table from an MKOSZ
basketball scoresheet PDF into a SQLite database.
"""

import fitz  # PyMuPDF
import sqlite3
import math
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(SCRIPT_DIR, "hun3k_125657.pdf")
DB_PATH = os.path.join(SCRIPT_DIR, "folyamatos_eredmeny.sqlite")

# --- Color mapping (RGB int from PyMuPDF → name) ---
COLOR_MAP = {
    0xFF0000: "red",
    0x000000: "black",
    0x088008: "green",
    0x0000FF: "blue",
}

def color_name(color_int):
    if color_int in COLOR_MAP:
        return COLOR_MAP[color_int]
    # Nearest match fallback
    best, best_dist = "black", float("inf")
    r, g, b = (color_int >> 16) & 0xFF, (color_int >> 8) & 0xFF, color_int & 0xFF
    for cint, cname in COLOR_MAP.items():
        cr, cg, cb = (cint >> 16) & 0xFF, (cint >> 8) & 0xFF, cint & 0xFF
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_dist:
            best, best_dist = cname, d
    return best

# --- Column boundaries (x-coordinates) ---
# 3 félidő × 2 oszlopcsoport-ismétlés × 5 oszlop = 30 fizikai oszlop.
# A hierarchia:
#   1. szint (félidő):        Első félidő | Második félidő | Hosszabbítás
#   2. szint (oszlopcsoport):  A, M, B — kétszer ismétlődik félidőnként (1. és 2.)
#   3. szint (egyedi oszlop):  A_-1 (mezszám), A_-2 (ponteredmény), M_ (perc),
#                              B_-1 (mezszám), B_-2 (ponteredmény)
# A határok a PDF-ben lévő téglalap x-koordinátáiból származnak.
COL_BOUNDS = [
    # 31 határérték, amelyek 30 oszlopot definiálnak.
    # Első félidő — 1. oszlopcsoport (A1-1, A1-2, M1, B1-1, B1-2)
    481, 503, 524, 543, 564,
    # Első félidő — 2. oszlopcsoport (A2-1, A2-2, M2, B2-1, B2-2)
    586, 605, 627, 646, 665,
    # Második félidő — 1. oszlopcsoport (A1-1, A1-2, M1, B1-1, B1-2)
    687, 708, 729, 749, 769,
    # Második félidő — 2. oszlopcsoport (A2-1, A2-2, M2, B2-1, B2-2)
    792, 811, 832, 851, 870,
    # Hosszabbítás — 1. oszlopcsoport (A1-1, A1-2, M1, B1-1, B1-2)
    891, 912, 933, 953, 973,
    # Hosszabbítás — 2. oszlopcsoport (A2-1, A2-2, M2, B2-1, B2-2)
    994, 1014, 1035, 1055, 1076,
    # Jobb szél
    1097,
]

# Félidő → oszlopcsoport-ismétlés (1., 2.) → egyedi oszlopok
# Oszlopcsoport-ismétlésenként 5 oszlop:
#   A_-1 = A csapat mezszám
#   A_-2 = A csapat ponteredmény (futó összeg)
#   M_   = megkezdett perc
#   B_-1 = B csapat mezszám
#   B_-2 = B csapat ponteredmény (futó összeg)
GROUPS = [
    ("Első félidő",    ["A1-1", "A1-2", "M1", "B1-1", "B1-2"]),   # 1. ismétlés
    ("Első félidő",    ["A2-1", "A2-2", "M2", "B2-1", "B2-2"]),   # 2. ismétlés
    ("Második félidő", ["A1-1", "A1-2", "M1", "B1-1", "B1-2"]),   # 1. ismétlés
    ("Második félidő", ["A2-1", "A2-2", "M2", "B2-1", "B2-2"]),   # 2. ismétlés
    ("Hosszabbítás",   ["A1-1", "A1-2", "M1", "B1-1", "B1-2"]),   # 1. ismétlés
    ("Hosszabbítás",   ["A2-1", "A2-2", "M2", "B2-1", "B2-2"]),   # 2. ismétlés
]

COLUMNS = []  # lista: (x_bal, x_jobb, header, col_name)
idx = 0
for gi, (header, names) in enumerate(GROUPS):
    for ci, cname in enumerate(names):
        left = COL_BOUNDS[idx]
        right = COL_BOUNDS[idx + 1]
        COLUMNS.append((left, right, header, cname))
        idx += 1

# --- Row boundaries ---
ROW_TOP = 306       # y-position of the top of row 1
ROW_HEIGHT = 26.05  # approximate height of each row
NUM_ROWS = 42

def get_row(y):
    """Return 1-based row number from y-coordinate."""
    r = int((y - ROW_TOP) / ROW_HEIGHT) + 1
    return max(1, min(r, NUM_ROWS))

def get_column(x):
    """Return (header, col_name) for the given x-coordinate, or None."""
    for left, right, header, cname in COLUMNS:
        if left <= x < right:
            return (header, cname)
    return None


def extract(pdf_path):
    doc = fitz.open(pdf_path)
    page = doc[0]

    # --- 1. Extract all characters in the table area ---
    blocks = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    raw_chars = []
    for block in blocks["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span.get("chars", []):
                    x0, y0, x1, y1 = ch["bbox"]
                    if x0 >= 480 and 300 < y0 < 1410 and ch["c"].strip():
                        raw_chars.append({
                            "c": ch["c"],
                            "x": x0,
                            "y": y0,
                            "x1": x1,
                            "y1": y1,
                            "color": span["color"],
                            "size": span["size"],
                        })

    # --- 2. Detect circles ---
    # A bekarikázott értékek kétféle jelentéssel bírnak:
    #   - Mezszám oszlopban (A_-1, B_-1): hárompontos kosár
    #   - Ponteredmény oszlopban (A_-2, B_-2): negyedvégi / mérkőzésvégi eredmény
    drawings = page.get_drawings()
    circles = []
    for d in drawings:
        rect = d["rect"]
        x0, y0, x1, y1 = rect
        if x0 < 475 or y0 < 290 or y1 > 1420:
            continue
        has_curve = any(item[0] == "c" for item in d["items"])
        w, h = x1 - x0, y1 - y0
        if has_curve and 5 < w < 25 and 5 < h < 25 and abs(w - h) < 5:
            circles.append((x0, y0, x1, y1))

    doc.close()

    # --- 3. Assign each character to a grid cell (row, col) ---
    # Group chars into cells
    cells = {}  # (row, header, col_name) → list of (x, char, color)
    for ch in raw_chars:
        col_info = get_column(ch["x"])
        if col_info is None:
            continue
        header, cname = col_info
        row = get_row(ch["y"])
        key = (row, header, cname)
        cells.setdefault(key, []).append((ch["x"], ch["c"], ch["color"]))

    # --- 4. Assemble cell values ---
    # Sort chars within each cell by x, then concatenate adjacent digits into numbers.
    # Characters separated by >12px gap are treated as separate values.
    records = []
    for (row, header, cname), char_list in sorted(cells.items()):
        char_list.sort(key=lambda t: t[0])

        # Group into tokens by proximity
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
            # Use the color of the first non-dash character, or first char
            color_val = token_chars[0][2]
            for _, c, col in token_chars:
                if c != "-":
                    color_val = col
                    break

            # Check if circled
            circled = 0
            for cx0, cy0, cx1, cy1 in circles:
                # Check if any char in this token overlaps the circle rect
                for chx, _, _ in token_chars:
                    if cx0 - 3 <= chx <= cx1 + 3:
                        ch_y = None
                        # Find the y of this char from raw_chars
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


def write_db(records, db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
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
    for r in records:
        c.execute(
            "INSERT INTO running_score (header, column_name, color, circled, row_number, character) VALUES (?, ?, ?, ?, ?, ?)",
            (r["header"], r["column"], r["color"], r["circled"], r["row_number"], r["character"]),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    records = extract(PDF_PATH)
    write_db(records, DB_PATH)

    print(f"Extracted {len(records)} records → {DB_PATH}")
    print()

    # Summary
    from collections import Counter
    print("By header:")
    for h, cnt in Counter(r["header"] for r in records).most_common():
        print(f"  {h}: {cnt}")
    print("By color:")
    for c, cnt in Counter(r["color"] for r in records).most_common():
        print(f"  {c}: {cnt}")
    print("By column:")
    for c, cnt in sorted(Counter(r["column"] for r in records).items()):
        print(f"  {c}: {cnt}")
    print(f"Circled: {sum(1 for r in records if r['circled'])}")
    print(f"Row range: {min(r['row_number'] for r in records)} - {max(r['row_number'] for r in records)}")
