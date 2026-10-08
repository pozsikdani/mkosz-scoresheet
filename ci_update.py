#!/usr/bin/env python3
"""
CI pipeline: scoresheet PDF letöltés és feldolgozás.

PBP scraping a mkosz-play-by-play repo-ban történik.
Dashboard generálás a mkosz-dashboard repo-ban történik.

Használat:
    python3 ci_update.py
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEASON = "x2627"
PDF_DIR = os.path.join(SCRIPT_DIR, "pdfs")
SCORESHEET_DB = os.path.join(SCRIPT_DIR, "scoresheet.sqlite")

# --- Scoresheet competitions (PDF-based) ---
SCORESHEET_COMPS = [
    # KÖZGÁZ-oldali (kozgazkosar.hu + mkosz-dashboard)
    {"comp": "hun3k", "county": None},          # NB2 Kelet — alapszakasz
    {"comp": "hun3_plya", "county": None},      # NB2 alsóházi rájátszás (később, ha bekerül)
    {"comp": "huna_cup", "county": None},       # Hepp Kupa (Öregek Kupája)
    # scout-web-oldali (mkosz-scout-web — a Játékosok tab player_game_stats-ához kell)
    {"comp": "hun2a", "county": None},          # NB1 B Piros alapszakasz
    {"comp": "hun2a_ply", "county": None},      # NB1 B Piros felső házi rájátszás
    {"comp": "hun2a_plya", "county": None},     # NB1 B Piros alsó házi rájátszás
]


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


def main():
    print("=" * 60)
    print(f"CI frissítés indítása — {SEASON}")
    print(f"  PDF mappa: {PDF_DIR}")
    print(f"  Scoresheet DB: {SCORESHEET_DB}")
    print("=" * 60)

    new_pdfs = download_and_extract_scoresheets()

    print(f"\n{'='*60}")
    print(f"Összefoglaló: {new_pdfs} új PDF")
    print("=" * 60)

    # Write output for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write("has_changes=true\n")


if __name__ == "__main__":
    main()
