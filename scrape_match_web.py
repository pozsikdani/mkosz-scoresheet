#!/usr/bin/env python3
"""
Fallback scraper a megye.hunbasket.hu meccs-adatlapokról.

Akkor használjuk amikor a jegyzőkönyv PDF képes formátumú (raszterkép)
és a PyMuPDF nem tud szöveget kinyerni belőle. Ilyenkor legalább a fő
meccs-infót (csapatok, dátum, végeredmény) a weboldalról pótoljuk.

Használat:
    from scrape_match_web import fetch_match_info_web
    info = fetch_match_info_web("x2526", "hun_bud_rkfb", "133", county="budapest")
    # -> dict insert_match() kompatibilis formában, vagy None
"""
from __future__ import annotations

import re
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Magyar hónap → szám
HU_MONTHS = {
    "január": 1, "február": 2, "március": 3, "április": 4,
    "május": 5, "június": 6, "július": 7, "augusztus": 8,
    "szeptember": 9, "október": 10, "november": 11, "december": 12,
}


def _fetch(url: str, timeout: int = 15) -> str | None:
    """HTTP GET with user agent, return text or None on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    [web fallback] letöltés hiba {url}: {e}")
        return None


def _parse_hu_date(text: str) -> str | None:
    """'2026. Április 17. péntek' → '2026-04-17'."""
    m = re.search(
        r"(\d{4})\.?\s*([A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]+)\s*(\d+)\.",
        text,
    )
    if not m:
        return None
    year, month_name, day = m.group(1), m.group(2).lower(), m.group(3)
    month = HU_MONTHS.get(month_name)
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def _find_match_url_for_pdf(
    season: str, comp_code: str, pdf_id: str, county: str
) -> str | None:
    """A bajnoksag-musor oldalról a PDF ID-hoz tartozó meccs URL megkeresése.

    A schedule oldal tartalmazza az összes meccs linkjét és hozzá a PDF URL-t.
    """
    schedule_url = (
        f"https://megye.hunbasket.hu/{county}/bajnoksag-musor/{season}/{comp_code}"
    )
    html = _fetch(schedule_url)
    if not html:
        return None

    # Keresünk olyan match-URL-t ami közelében van a kérdéses PDF link.
    # A formátum: <a href=".../merkozes/x2526/hun_bud_rkfb/9103533">...
    # és később ugyanabban a block-ban a PDF link: hun_bud_rkfb_133.pdf
    pdf_filename = f"{comp_code}_{pdf_id}.pdf"

    # A schedule oldalon nincs közvetlen link a PDF-re (csak a meccs oldalakon),
    # tehát brute-force-tal kell: minden match URL-t lekérünk és megnézzük
    # melyikre mutat a PDF. Ez lassú — cache-eljük session szinten.
    match_urls = re.findall(
        rf'href="(https://megye\.hunbasket\.hu/{re.escape(county)}/merkozes/'
        rf'{re.escape(season)}/{re.escape(comp_code)}/\d+)"',
        html,
    )
    match_urls = list(dict.fromkeys(match_urls))  # dedup preserve order

    for match_url in match_urls:
        page = _fetch(match_url)
        if page and pdf_filename in page:
            return match_url

    return None


def _parse_match_page(html: str, pdf_id: str) -> dict | None:
    """A meccs-adatlap HTML parse-olása → match_info dict."""
    # Dátum
    match_date = _parse_hu_date(html)

    # Csapatok
    home_m = re.search(r'pbp-head-name home">\s*([^<]+?)\s*<', html)
    away_m = re.search(r'pbp-head-name away">\s*([^<]+?)\s*<', html)
    if not home_m or not away_m:
        return None
    team_a = home_m.group(1).strip()
    team_b = away_m.group(1).strip()

    # Végeredmény: '78 - 69' format
    score_m = re.search(r'pbp-head-result-cont">\s*(\d+)\s*-\s*(\d+)', html)
    if not score_m:
        return None
    score_a, score_b = int(score_m.group(1)), int(score_m.group(2))

    # Időpont (opcionális)
    time_m = re.search(r"(\d{1,2}):(\d{2})", html)
    match_time = f"{time_m.group(1)}:{time_m.group(2)}" if time_m else None

    # Helyszín (opcionális — gyakran nincs a meccs oldalon)
    venue = None

    winner = None
    if score_a > score_b:
        winner = "A"
    elif score_b > score_a:
        winner = "B"

    # Egyedi match_id — hogy ne ütközzön a scoresheet-ből származókkal,
    # "WEB-{comp_prefix}-{pdf_id}" formát használunk.
    match_id = f"WEB-{pdf_id}"

    return {
        "match_id": match_id,
        "team_a": team_a.upper(),  # konzisztens a többi meccshez
        "team_b": team_b.upper(),
        "venue": venue,
        "match_date": match_date or "0000-00-00",
        "match_time": match_time,
        "score_a": score_a,
        "score_b": score_b,
        "winner": winner,
        "closure_timestamp": None,
    }


def fetch_match_info_web(
    season: str,
    comp_code: str,
    pdf_id: str,
    county: str | None = None,
) -> dict | None:
    """Képes PDF fallback: megye.hunbasket.hu-ról szedi a fő meccs-infót.

    Args:
        season: pl. "x2526"
        comp_code: pl. "hun_bud_rkfb"
        pdf_id: pl. "133" (PDF filename-ből: hun_bud_rkfb_133.pdf)
        county: pl. "budapest" — megyei bajnokságokhoz

    Returns:
        dict insert_match() kompatibilis formában, vagy None ha nem sikerült.
    """
    if not county:
        # Országos bajnokságok (mkosz.hu) nem támogatottak egyelőre —
        # ott a képes PDF-ek ritkák (Kandó SC esetén).
        print(f"    [web fallback] country-level PDF nem támogatott: {comp_code}")
        return None

    match_url = _find_match_url_for_pdf(season, comp_code, pdf_id, county)
    if not match_url:
        print(f"    [web fallback] nem található match URL: {comp_code}_{pdf_id}")
        return None

    page = _fetch(match_url)
    if not page:
        return None

    info = _parse_match_page(page, pdf_id)
    if info:
        print(
            f"    [web fallback] ✓ {info['team_a']} vs {info['team_b']} "
            f"({info['score_a']}-{info['score_b']}, {info['match_date']})"
        )
    return info


# CLI teszt
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Használat: scrape_match_web.py <season> <comp_code> <pdf_id> [county]")
        sys.exit(1)
    season, comp_code, pdf_id = sys.argv[1], sys.argv[2], sys.argv[3]
    county = sys.argv[4] if len(sys.argv) > 4 else None
    result = fetch_match_info_web(season, comp_code, pdf_id, county)
    print(result)
