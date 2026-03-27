#!/usr/bin/env python3
"""
CI pipeline: scoresheet PDF letöltés, feldolgozás, PBP konverzió.

Dashboard generálás a mkosz-dashboard repo-ban történik.

Használat:
    python3 ci_update.py                  # Teljes pipeline
    PBP_DB_PATH=./pbp.sqlite python3 ci_update.py   # CI-ben
"""

import os
import sqlite3
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEASON = "x2526"
PDF_DIR = os.path.join(SCRIPT_DIR, "pdfs")
SCORESHEET_DB = os.path.join(SCRIPT_DIR, "scoresheet.sqlite")
PBP_DB = os.environ.get(
    "PBP_DB_PATH",
    os.path.expanduser("~/Desktop/claudecode/mkosz-play-by-play/pbp.sqlite"),
)

# PBP repo location (CI: cloned to /tmp/mkosz-pbp, local: sibling dir)
PBP_REPO = os.environ.get(
    "PBP_REPO",
    os.path.expanduser("~/Desktop/claudecode/mkosz-play-by-play"),
)

# --- Scoresheet competitions (PDF-based) ---
SCORESHEET_COMPS = [
    # NB2 — mind az 5 csoport
    {"comp": "hun3ki", "county": None},
    {"comp": "hun3koa", "county": None},
    {"comp": "hun3kob", "county": None},
    {"comp": "hun3k", "county": None},
    {"comp": "hun3n", "county": None},
    # Budapesti bajnokságok
    {"comp": "whun_bud_na", "county": "budapest"},
    {"comp": "hun_bud_rkfb", "county": "budapest"},
]

# --- PBP competitions (HTML-based, MEFOB) ---
PBP_COMPS = [
    {"comp": "whun_univn"},
    {"comp": "hun_univn"},
]


def _ensure_pbp_tables(db_path):
    """Ensure PBP database has all required tables."""
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if 'player_stats' not in tables:
        print(f"  ⚠ player_stats tábla hiányzik, létrehozás...")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS player_stats (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id        TEXT NOT NULL,
                team            TEXT NOT NULL CHECK (team IN ('A', 'B')),
                player_name     TEXT NOT NULL,
                is_starter      INTEGER NOT NULL DEFAULT 0,
                minutes         INTEGER NOT NULL DEFAULT 0,
                plus_minus      INTEGER NOT NULL DEFAULT 0,
                val             INTEGER NOT NULL DEFAULT 0,
                ts_pct          REAL,
                efg_pct         REAL,
                game_score      REAL,
                usg_pct         REAL,
                ast_to          REAL,
                tov_pct         REAL,
                UNIQUE(match_id, team, player_name)
            );
        """)
        conn.commit()
    conn.close()


def download_and_extract_scoresheets():
    """Download new PDFs and extract to SQLite. Returns count of new PDFs."""
    sys.path.insert(0, SCRIPT_DIR)
    from download_scoresheets import download_all

    total_new = 0
    for cfg in SCORESHEET_COMPS:
        comp = cfg["comp"]
        county = cfg.get("county")
        label = f"{comp} (county: {county})" if county else comp
        print(f"\n{'='*60}")
        print(f"Scoresheet letöltés: {label}")
        print(f"{'='*60}")
        try:
            result = download_all(SEASON, comp, PDF_DIR, county=county)
            downloaded = result[1]
            total_new += downloaded
        except Exception as e:
            print(f"  HIBA ({comp}): {e}")

    # Extract all PDFs to SQLite (incremental — skips already processed)
    print(f"\n{'='*60}")
    print("Scoresheet feldolgozás")
    print(f"{'='*60}")
    try:
        subprocess.run(
            [
                sys.executable,
                os.path.join(SCRIPT_DIR, "extract_scoresheet.py"),
                PDF_DIR,
                "--db",
                SCORESHEET_DB,
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  Extract hiba: {e}")

    return total_new


def update_pbp_teams():
    """Parse new PBP matches. Returns count of new matches."""
    # Import parse_pbp from PBP repo
    pbp_dir = PBP_REPO
    if not os.path.isdir(pbp_dir):
        print(f"PBP repo nem található: {pbp_dir} — PBP frissítés kihagyva")
        return 0

    sys.path.insert(0, pbp_dir)
    try:
        from parse_pbp import create_db, delete_match, match_exists, process_match
    except ImportError as e:
        print(f"PBP import hiba: {e} — PBP frissítés kihagyva")
        return 0

    # Reuse scoresheet's discover_game_ids for PBP match discovery
    sys.path.insert(0, SCRIPT_DIR)
    from download_scoresheets import discover_game_ids

    total_new = 0
    conn = create_db(PBP_DB)

    for cfg in PBP_COMPS:
        comp = cfg["comp"]
        print(f"\n{'='*60}")
        print(f"PBP frissítés: {comp}")
        print(f"{'='*60}")

        try:
            game_ids = discover_game_ids(SEASON, comp)
        except Exception as e:
            print(f"  Discovery hiba ({comp}): {e}")
            continue

        new_count = 0
        for gid in game_ids:
            match_id = f"{comp}_{gid}"
            if match_exists(conn, match_id):
                continue
            try:
                process_match(SEASON, comp, str(gid), PBP_DB)
                # Check if match has actual events (skip future matches with 0-0)
                event_count = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE match_id = ?",
                    (match_id,),
                ).fetchone()[0]
                if event_count == 0:
                    delete_match(conn, match_id)
                    print(f"  {match_id} — jövőbeli meccs (0 esemény), kihagyva")
                else:
                    new_count += 1
                time.sleep(0.5)  # Be polite
            except Exception as e:
                print(f"  PBP hiba ({match_id}): {e}")

        print(f"  {new_count} új meccs feldolgozva ({comp})")
        total_new += new_count

    conn.close()

    # Ensure PBP DB has all tables (WAL checkpoint might not have flushed)
    _ensure_pbp_tables(PBP_DB)

    # Convert PBP → scoresheet schema
    if total_new > 0:
        print(f"\n{'='*60}")
        print("PBP → scoresheet konverzió")
        print(f"{'='*60}")
        for cfg in PBP_COMPS:
            try:
                subprocess.run(
                    [
                        sys.executable,
                        os.path.join(SCRIPT_DIR, "pbp_to_scoresheet.py"),
                        "--pbp-db",
                        PBP_DB,
                        "--target-db",
                        SCORESHEET_DB,
                        "--comp",
                        cfg["comp"],
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"  Konverzió hiba ({cfg['comp']}): {e}")

    return total_new


def main():
    print("=" * 60)
    print(f"CI frissítés indítása — {SEASON}")
    print(f"  PDF mappa: {PDF_DIR}")
    print(f"  Scoresheet DB: {SCORESHEET_DB}")
    print(f"  PBP DB: {PBP_DB}")
    print(f"  PBP repo: {PBP_REPO}")
    print("=" * 60)

    new_pdfs = download_and_extract_scoresheets()
    new_pbp = update_pbp_teams()

    print(f"\n{'='*60}")
    print(f"Összefoglaló: {new_pdfs} új PDF, {new_pbp} új PBP meccs")
    print("=" * 60)

    # Write output for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write("has_changes=true\n")


if __name__ == "__main__":
    main()
