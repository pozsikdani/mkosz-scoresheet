#!/usr/bin/env python3
"""
MKOSZ jegyzőkönyv PDF letöltő.

Automatikusan felfedezi és letölti egy adott bajnokság összes
jegyzőkönyv PDF-jét az MKOSZ weboldaláról.

Használat:
    python3 download_scoresheets.py x2526 hun3kob ./pdfs/
    python3 download_scoresheets.py x2526 hun3kob --list-only
    python3 download_scoresheets.py x2526 hun3kob ./pdfs/ --process --db season.sqlite
"""

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error


SCHEDULE_URL = "https://mkosz.hu/bajnoksag-musor/{season}/{competition}/"
PDF_BASE_URL = "https://hunbasketimg.webpont.com/pdf/{season}/{competition}_{game_id}.pdf"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def discover_game_ids(season, competition):
    """Fetch the schedule page and extract all game IDs."""
    url = SCHEDULE_URL.format(season=season, competition=competition)
    print(f"Műsor oldal letöltése: {url}")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  HIBA: HTTP {e.code} — {url}")
        return []
    except urllib.error.URLError as e:
        print(f"  HIBA: {e.reason} — {url}")
        return []

    # Extract game IDs from links like: /merkozes/x2526/hun3kob/hun3kob_125843
    pattern = rf"{re.escape(competition)}_(\d+)"
    ids = sorted(set(int(m) for m in re.findall(pattern, html)))
    print(f"  {len(ids)} meccs azonosító találva")
    return ids


def download_pdf(season, competition, game_id, output_dir):
    """Download a single scoresheet PDF. Returns path or None on error."""
    filename = f"{competition}_{game_id}.pdf"
    filepath = os.path.join(output_dir, filename)

    if os.path.exists(filepath):
        return filepath  # already downloaded

    url = PDF_BASE_URL.format(
        season=season, competition=competition, game_id=game_id
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(filepath, "wb") as f:
            f.write(data)
        return filepath
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # PDF not yet available (future match)
        print(f"  HIBA: HTTP {e.code} — {filename}")
        return None
    except urllib.error.URLError as e:
        print(f"  HIBA: {e.reason} — {filename}")
        return None


def download_all(season, competition, output_dir):
    """Discover and download all scoresheets.
    Returns (total, downloaded, skipped, errors)."""

    game_ids = discover_game_ids(season, competition)
    if not game_ids:
        print("Nem található meccs azonosító.")
        return 0, 0, 0, 0

    os.makedirs(output_dir, exist_ok=True)

    total = len(game_ids)
    downloaded = 0
    skipped = 0
    errors = 0
    not_available = 0

    for i, gid in enumerate(game_ids, 1):
        filename = f"{competition}_{gid}.pdf"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath):
            skipped += 1
            print(f"  [{i:>{len(str(total))}}/{total}] {filename} — már megvan")
            continue

        result = download_pdf(season, competition, gid, output_dir)
        if result:
            downloaded += 1
            print(f"  [{i:>{len(str(total))}}/{total}] {filename} ✓")
        else:
            # Check if it's a future match (404) vs real error
            not_available += 1
            print(f"  [{i:>{len(str(total))}}/{total}] {filename} — nem elérhető")

        # Be polite: small delay between downloads
        if i < total:
            time.sleep(0.3)

    print()
    print(f"Összesen: {total} meccs")
    print(f"  Letöltve:     {downloaded}")
    print(f"  Már megvolt:  {skipped}")
    print(f"  Nem elérhető: {not_available}")
    if errors:
        print(f"  Hibás:        {errors}")

    return total, downloaded, skipped, errors


def main():
    parser = argparse.ArgumentParser(
        description="MKOSZ jegyzőkönyv PDF-ek automatikus letöltése"
    )
    parser.add_argument(
        "season",
        help="Szezon kód (pl. x2526 = 2025/2026)",
    )
    parser.add_argument(
        "competition",
        help="Bajnokság kód (pl. hun3kob = NB2 Közép B)",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Letöltési mappa (kötelező, kivéve --list-only)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Csak a meccs azonosítók kilistázása, letöltés nélkül",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Letöltés után extract_scoresheet.py futtatása",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Adatbázis fájl (--process esetén)",
    )
    args = parser.parse_args()

    if args.list_only:
        ids = discover_game_ids(args.season, args.competition)
        if ids:
            for gid in ids:
                print(f"  {args.competition}_{gid}.pdf")
            print(f"\nÖsszesen: {len(ids)} meccs")
        return

    if not args.output_dir:
        parser.error("output_dir kötelező (kivéve --list-only)")

    total, downloaded, skipped, errors = download_all(
        args.season, args.competition, args.output_dir
    )

    if args.process and (downloaded > 0 or skipped > 0):
        print()
        print("=" * 60)
        print("Feldolgozás indul...")
        print("=" * 60)
        cmd = [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "extract_scoresheet.py"),
            args.output_dir,
        ]
        if args.db:
            cmd += ["--db", args.db]
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
