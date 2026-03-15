#!/usr/bin/env python3
"""
MKOSZ jegyzőkönyv PDF letöltő.

Automatikusan felfedezi és letölti egy adott bajnokság összes
jegyzőkönyv PDF-jét az MKOSZ weboldaláról.

Támogatja az országos (mkosz.hu) és a megyei (megye.hunbasket.hu)
bajnokságokat is.

Használat:
    # Országos bajnokság (MKOSZ):
    python3 download_scoresheets.py x2526 hun3kob ./pdfs/
    python3 download_scoresheets.py x2526 hun3kob --list-only
    python3 download_scoresheets.py x2526 hun3kob ./pdfs/ --process --db season.sqlite

    # Megyei bajnokság:
    python3 download_scoresheets.py x2526 whun_bud_na ./pdfs/ --county budapest
    python3 download_scoresheets.py x2526 whun_bud_na --list-only --county budapest
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

# Megyei bajnokság URL-ek
COUNTY_SCHEDULE_URL = "https://megye.hunbasket.hu/{county}/bajnoksag-musor/{season}/{competition}"
COUNTY_MATCH_URL = "https://megye.hunbasket.hu/{county}/merkozes/{season}/{competition}/{match_id}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _fetch_html(url):
    """Fetch a URL and return HTML string, or None on error."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  HIBA: HTTP {e.code} — {url}")
        return None
    except urllib.error.URLError as e:
        print(f"  HIBA: {e.reason} — {url}")
        return None


def discover_game_ids(season, competition):
    """Fetch the MKOSZ schedule page and extract all game IDs."""
    url = SCHEDULE_URL.format(season=season, competition=competition)
    print(f"Műsor oldal letöltése: {url}")

    html = _fetch_html(url)
    if not html:
        return []

    # Extract game IDs from links like: /merkozes/x2526/hun3kob/hun3kob_125843
    pattern = rf"{re.escape(competition)}_(\d+)"
    ids = sorted(set(int(m) for m in re.findall(pattern, html)))
    print(f"  {len(ids)} meccs azonosító találva")
    return ids


def discover_county_pdfs(season, competition, county):
    """Discover PDF URLs from a county-level (megye.hunbasket.hu) competition.

    County-level PDFs use sequential document numbers that differ from match IDs.
    We must visit each match detail page to find the actual PDF link.

    Returns list of (doc_number, pdf_url) tuples.
    """
    # Step 1: Get all match IDs from the competition schedule page
    url = COUNTY_SCHEDULE_URL.format(
        county=county, season=season, competition=competition
    )
    print(f"Megyei műsor oldal letöltése: {url}")

    html = _fetch_html(url)
    if not html:
        return []

    # Extract match IDs from links like: /merkozes/x2526/whun_bud_na/9104307
    pattern = rf"/merkozes/{re.escape(season)}/{re.escape(competition)}/(\d+)"
    match_ids = sorted(set(re.findall(pattern, html)))
    print(f"  {len(match_ids)} meccs link találva")

    if not match_ids:
        return []

    # Step 2: Visit each match page to find PDF links
    pdf_entries = []
    total = len(match_ids)

    for i, mid in enumerate(match_ids, 1):
        match_url = COUNTY_MATCH_URL.format(
            county=county, season=season, competition=competition, match_id=mid
        )

        match_html = _fetch_html(match_url)
        if not match_html:
            print(f"  [{i:>{len(str(total))}}/{total}] Meccs {mid} — oldal nem elérhető")
            continue

        # Find PDF link: href containing hunbasketimg.webpont.com/pdf/
        pdf_pattern = rf'https?://hunbasketimg\.webpont\.com/pdf/{re.escape(season)}/{re.escape(competition)}_(\d+)\.pdf'
        pdf_matches = re.findall(pdf_pattern, match_html)

        if pdf_matches:
            doc_num = pdf_matches[0]
            pdf_url = f"https://hunbasketimg.webpont.com/pdf/{season}/{competition}_{doc_num}.pdf"
            pdf_entries.append((doc_num, pdf_url))
            print(f"  [{i:>{len(str(total))}}/{total}] Meccs {mid} → PDF #{doc_num} ✓")
        else:
            print(f"  [{i:>{len(str(total))}}/{total}] Meccs {mid} — nincs PDF link")

        # Be polite: small delay between requests
        if i < total:
            time.sleep(0.3)

    # Deduplicate (multiple match links can point to same PDF)
    seen = set()
    unique_entries = []
    for doc_num, pdf_url in pdf_entries:
        if doc_num not in seen:
            seen.add(doc_num)
            unique_entries.append((doc_num, pdf_url))

    print(f"\n  {len(unique_entries)} egyedi PDF találva")
    return unique_entries


def download_pdf(season, competition, game_id, output_dir, pdf_url=None):
    """Download a single scoresheet PDF. Returns path or None on error.

    If pdf_url is provided, use it directly (county mode).
    Otherwise construct the URL from season/competition/game_id (MKOSZ mode).
    """
    filename = f"{competition}_{game_id}.pdf"
    filepath = os.path.join(output_dir, filename)

    if os.path.exists(filepath):
        return filepath  # already downloaded

    if pdf_url is None:
        pdf_url = PDF_BASE_URL.format(
            season=season, competition=competition, game_id=game_id
        )
    req = urllib.request.Request(pdf_url, headers={"User-Agent": USER_AGENT})
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


def download_all(season, competition, output_dir, county=None):
    """Discover and download all scoresheets.
    Returns (total, downloaded, skipped, errors).

    If county is provided, uses county-level discovery (megye.hunbasket.hu).
    Otherwise uses MKOSZ national discovery (mkosz.hu).
    """
    if county:
        return _download_all_county(season, competition, output_dir, county)

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


def _download_all_county(season, competition, output_dir, county):
    """Discover and download all scoresheets from a county-level competition.
    Returns (total, downloaded, skipped, errors)."""

    pdf_entries = discover_county_pdfs(season, competition, county)
    if not pdf_entries:
        print("Nem található PDF jegyzőkönyv.")
        return 0, 0, 0, 0

    os.makedirs(output_dir, exist_ok=True)

    total = len(pdf_entries)
    downloaded = 0
    skipped = 0
    not_available = 0

    print(f"\nPDF-ek letöltése ({total} db)...")
    for i, (doc_num, pdf_url) in enumerate(pdf_entries, 1):
        filename = f"{competition}_{doc_num}.pdf"
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath):
            skipped += 1
            print(f"  [{i:>{len(str(total))}}/{total}] {filename} — már megvan")
            continue

        result = download_pdf(season, competition, doc_num, output_dir, pdf_url=pdf_url)
        if result:
            downloaded += 1
            print(f"  [{i:>{len(str(total))}}/{total}] {filename} ✓")
        else:
            not_available += 1
            print(f"  [{i:>{len(str(total))}}/{total}] {filename} — nem elérhető")

        # Be polite: small delay between downloads
        if i < total:
            time.sleep(0.3)

    print()
    print(f"Összesen: {total} PDF")
    print(f"  Letöltve:     {downloaded}")
    print(f"  Már megvolt:  {skipped}")
    print(f"  Nem elérhető: {not_available}")

    return total, downloaded, skipped, 0


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
    parser.add_argument(
        "--county",
        default=None,
        help="Megyei bajnokság: megye neve (pl. budapest). "
             "Ha megadva, megye.hunbasket.hu-ról tölti le a PDF-eket.",
    )
    args = parser.parse_args()

    if args.list_only:
        if args.county:
            entries = discover_county_pdfs(args.season, args.competition, args.county)
            if entries:
                for doc_num, pdf_url in entries:
                    print(f"  {args.competition}_{doc_num}.pdf")
                print(f"\nÖsszesen: {len(entries)} PDF")
        else:
            ids = discover_game_ids(args.season, args.competition)
            if ids:
                for gid in ids:
                    print(f"  {args.competition}_{gid}.pdf")
                print(f"\nÖsszesen: {len(ids)} meccs")
        return

    if not args.output_dir:
        parser.error("output_dir kötelező (kivéve --list-only)")

    total, downloaded, skipped, errors = download_all(
        args.season, args.competition, args.output_dir, county=args.county
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
