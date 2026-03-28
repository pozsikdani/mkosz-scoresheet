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
SEASON = "x2526"
PDF_DIR = os.path.join(SCRIPT_DIR, "pdfs")
SCORESHEET_DB = os.path.join(SCRIPT_DIR, "scoresheet.sqlite")

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
