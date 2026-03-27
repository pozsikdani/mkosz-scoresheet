# mkosz-scoresheet

Downloads MKOSZ basketball scoresheet PDFs and extracts structured data into a SQLite database. Covers all NB2 groups plus Budapest regional leagues.

Dashboard generation has moved to [mkosz-dashboard](https://github.com/pozsikdani/mkosz-dashboard).

## What it does

1. **Downloads** scoresheet PDFs from hunbasketimg.webpont.com (`download_scoresheets.py`)
2. **Extracts** structured data via character-level PDF parsing with PyMuPDF — no OCR (`extract_scoresheet.py`)
3. **Converts** play-by-play data to scoresheet schema for MEFOB leagues (`pbp_to_scoresheet.py`)
4. Produces `scoresheet.sqlite` with 12 normalized tables (~370 matches, 35K scoring events)

## Usage

```bash
pip install PyMuPDF requests beautifulsoup4

# Download PDFs for a competition
python3 download_scoresheets.py x2526 hun3k ./pdfs/

# Extract all PDFs to database
python3 extract_scoresheet.py ./pdfs/ --db scoresheet.sqlite

# Run full CI pipeline (download + extract + PBP conversion)
python3 ci_update.py
```

## Competitions

| Code | League |
|---|---|
| hun3ki | NB2 Kiemelt |
| hun3koa | NB2 Kozep A |
| hun3kob | NB2 Kozep B |
| hun3k | NB2 Kelet |
| hun3n | NB2 Nyugat |
| whun_bud_na | Women's A (Budapest) |
| hun_bud_rkfb | Regional (Budapest) |

## Automation

`daily-extract.yml` runs at 6:00 UTC — downloads new PDFs, extracts, converts PBP, commits updated `scoresheet.sqlite`.
