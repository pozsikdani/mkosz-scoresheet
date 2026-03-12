# MKOSZ Scoresheet Extractor — Project Documentation

> Ez a fájl azért készült, hogy egy új Claude session (vagy bárki más) teljes kontextust kapjon a projektről.
> Utolsó frissítés: 2026-03-12.

## Mi ez a projekt?

Automatikus feldolgozó rendszer, ami a **Magyar Kosárlabda Szövetség (MKOSZ)** digitális jegyzőkönyv PDF-jeiből strukturált SQLite adatbázist készít. A PDF-ekből karakterszintű pozíció-alapú kinyeréssel (PyMuPDF, NEM OCR) dolgozik.

A rendszer képes egy teljes bajnokság összes jegyzőkönyvét automatikusan letölteni az MKOSZ weboldaláról és feldolgozni.

## Fájlstruktúra

```
mkosz-scoresheet/
├── extract_scoresheet.py    # Fő feldolgozó script (~1900 sor)
├── download_scoresheets.py  # Automatikus PDF letöltő
├── README.md                # Eredeti dokumentáció (elavult, egyetlen meccsre vonatkozik)
├── CLAUDE.md                # ← EZ A FÁJL — teljes projekt kontextus
├── .gitignore               # *.sqlite, pdfs/
├── pdfs/                    # Letöltött PDF-ek (gitignore-ban, regenerálható)
│   ├── hun3ki_*.pdf         # NB2 Kiemelt (90 meccs)
│   ├── hun3koa_*.pdf        # NB2 Közép A (72 meccs)
│   ├── hun3kob_*.pdf        # NB2 Közép B (72 meccs)
│   ├── hun3k_*.pdf          # NB2 Kelet (72 meccs)
│   └── hun3n_*.pdf          # NB2 Nyugat (72 meccs)
├── nb2_full.sqlite          # Teljes NB2 adatbázis (gitignore-ban, regenerálható)
└── season.sqlite            # Csak Közgáz meccsek (gitignore-ban)
```

## Használat

### Előfeltétel
```bash
pip install PyMuPDF
```

### Teljes NB2 szezon letöltése és feldolgozása

```bash
# 1. Letöltés — mind az 5 csoport
python3 download_scoresheets.py x2526 hun3ki  ./pdfs/   # Kiemelt (90 meccs)
python3 download_scoresheets.py x2526 hun3koa ./pdfs/   # Közép A (72 meccs)
python3 download_scoresheets.py x2526 hun3kob ./pdfs/   # Közép B (72 meccs)
python3 download_scoresheets.py x2526 hun3k   ./pdfs/   # Kelet (72 meccs)
python3 download_scoresheets.py x2526 hun3n   ./pdfs/   # Nyugat (72 meccs)

# 2. Feldolgozás — egy parancs az összesre
python3 extract_scoresheet.py ./pdfs/ --db nb2_full.sqlite

# Vagy újrafeldolgozás (meglévő meccseket is felülírja):
python3 extract_scoresheet.py ./pdfs/ --db nb2_full.sqlite --force
```

### Egyéb CLI opciók

```bash
# Csak meccs-ID-k listázása (letöltés nélkül)
python3 download_scoresheets.py x2526 hun3kob --list-only

# Egyetlen PDF feldolgozása
python3 extract_scoresheet.py --single ./pdfs/hun3kob_125843.pdf --db test.sqlite

# Letöltés + azonnali feldolgozás
python3 download_scoresheets.py x2526 hun3kob ./pdfs/ --process --db season.sqlite
```

## URL séma (MKOSZ)

```
Műsor oldal:  https://mkosz.hu/bajnoksag-musor/{season}/{competition}/
PDF letöltés: https://hunbasketimg.webpont.com/pdf/{season}/{competition}_{game_id}.pdf
```

### Szezon kódok
- `x2526` = 2025/2026
- `x2425` = 2024/2025

### Bajnokság kódok (NB2, 2025/2026)

| Kód | Bajnokság | Meccsek |
|-----|-----------|---------|
| `hun3ki`  | NB2 Kiemelt | 90 |
| `hun3koa` | NB2 Közép A | 72 |
| `hun3kob` | NB2 Közép B | 72 |
| `hun3k`   | NB2 Kelet   | 72 |
| `hun3n`   | NB2 Nyugat  | 72 |

## Adatbázis séma

12 tábla, minden tábla `match_id` foreign key-jel az azonos adatbázison belüli `matches` táblára.

### Fő táblák

| Tábla | Leírás | ~Sorok (360 meccs) |
|-------|--------|---:|
| `matches` | Meccs metaadatok (csapatok, eredmény, dátum, helyszín) | 360 |
| `players` | Játékos registry meccsekre bontva (név, mezszám, igazolásszám, szerep) | 8,000 |
| `scoring_events` | Minden egyes pont-esemény (ki, mikor, hogyan dobott) | 34,000 |
| `player_game_stats` | Meccsenkénti box score játékosonként (pont, 2PT, 3PT, FT, faultok) | 7,100 |
| `personal_fouls` | Egyéni faultok (perc, negyed, típus, kategória) | 11,400 |
| `quarter_scores` | Negyedenkénti pontszámok | 1,800 |
| `running_score` | Nyers "Folyamatos Eredmény" grid (minden cella) | 77,000 |
| `team_fouls` | Csapat-faultok negyedenként | 2,900 |
| `timeouts` | Időkérések | 1,600 |
| `referees` | Játékvezetők | 720 |
| `officials` | Hivatalos személyek (jegyző, időmérő) | 1,050 |
| `extraction_log` | Feldolgozási metaadatok (futásidő, státusz, hibák) | — |

### Kulcs-oszlopok

**`matches`**: `match_id` (PK, pl. "F2KB-0011"), `team_a`, `team_b`, `score_a`, `score_b`, `match_date`, `venue`, `source_pdf`

**`players`**: `match_id`, `team` (A/B), `license_number` (MKOSZ igazolásszám — **AZ EGYETLEN EGYEDI JÁTÉKOS-AZONOSÍTÓ**), `name`, `jersey_number`, `role` (player/captain/coach/assistant_coach), `starter` (0/1), `entry_quarter` (1-4)

**`scoring_events`**: `match_id`, `event_seq`, `quarter` (1-4), `team`, `jersey_number`, `license_number`, `points` (0/1/2/3), `shot_type` (2FG/3FG/FT), `made` (0/1), `score_a`, `score_b`

**`player_game_stats`**: `match_id`, `team`, `license_number`, `name`, `jersey_number`, `points`, `fg2_made`, `fg3_made`, `ft_made`, `ft_attempted`, `personal_fouls`, `starter`, `entry_quarter`

**`personal_fouls`**: `match_id`, `team`, `jersey_number`, `foul_number` (1-5), `minute`, `quarter`, `foul_type` (defensive/offensive), `foul_category` (NULL/T/U/B/C/D), `free_throws`, `offsetting`

## Fontos tervezési döntések

### license_number az egyedi azonosító
- A `license_number` (MKOSZ igazolásszám) az EGYETLEN megbízható játékos-azonosító
- Egy játékos **különböző mezszámot viselhet** különböző meccseken
- Két játékosnak **lehet ugyanaz a neve**
- A `scoring_events` és `player_game_stats` JOIN-ok `license_number`-t használnak (jersey_number fallback-kel)

### Jersey reconciliation
- A running score gridben a mezszámok néha csonkítva jelennek meg (pl. 17 → 7), mert az első számjegy a cellahatáron kívülre esik
- A `reconcile_jersey_numbers()` függvény a scoring_events beszúrása UTÁN fut: az "árva" mezszámokat (amik nem egyeznek egyetlen játékossal sem) az utolsó számjegy alapján párosítja vissza (pl. 7 → 17, ha csak egy 7-re végződő mez van)

### Név-kinyerés robusztussága
1. **Overflow szűrés**: Hosszú nevek a PDF-ben két sorba törnek; az előző sor átfolyó karaktereit y-pozíció alapján szűrjük (8px küszöb a sor tetejétől)
2. **Soronkénti assembly**: Ha egy név a saját celláján belül törik két sorba, a karaktereket soronként (y-line) assembleljük, nem x-pozíció szerint — elkerüli az interleaving-et
3. **Digit szűrés**: A nevek nem tartalmaznak számjegyeket; ez megakadályozza, hogy a balra csúszott mezszám első digitje a név részeként jelenjen meg

### PDF template detekció
- Két template létezik: TYPE1 (`off=0`) és TYPE2 (`off_body=-20px`)
- A detekció a match_id "F" karakterének y-pozíciója alapján történik (413 vs 393)
- `COL_BOUNDS` — a running score grid oszlophatárai, néhol -4px korrekcióval

## Pontossági metrikák (2025-26 szezon, 360 meccs)

| Csoport | SE (scoring events) | PGS (player game stats) |
|---------|:---:|:---:|
| Kiemelt | 86/90 (96%) | — |
| Közép A | 62/64 (97%) | — |
| **Közép B** | **71/72 (99%)** | **71/72** |
| Kelet | 69/71 (97%) | — |
| Nyugat | 63/63 **(100%)** | — |
| **Összesen** | **351/360 (97.5%)** | **344/360 (95.6%)** |

A hibák jellemzően -2 vagy -3 pont eltérések, a running score grid szélén csonkított mezszámok miatt.

## Hasznos lekérdezések

### Egy csapat összes játékosa szezon statisztikákkal
```sql
WITH kozgaz AS (
    SELECT match_id,
           CASE WHEN team_a LIKE '%KÖZGÁZ%' THEN 'A' ELSE 'B' END as kg_team
    FROM matches
)
SELECT
    p.license_number,
    (SELECT name FROM players p2
     WHERE p2.license_number = p.license_number
     GROUP BY name ORDER BY LENGTH(name) DESC LIMIT 1) as best_name,
    COUNT(DISTINCT CASE WHEN p.entry_quarter IS NOT NULL THEN p.match_id END) as games,
    COALESCE(SUM(pgs.points), 0) as total_pts,
    ROUND(1.0 * COALESCE(SUM(pgs.points), 0) /
        NULLIF(COUNT(DISTINCT CASE WHEN p.entry_quarter IS NOT NULL THEN p.match_id END), 0), 1) as ppg
FROM players p
JOIN kozgaz k ON p.match_id = k.match_id AND p.team = k.kg_team
LEFT JOIN player_game_stats pgs
    ON pgs.match_id = p.match_id AND pgs.license_number = p.license_number AND pgs.team = p.team
WHERE p.role IN ('player','captain')
GROUP BY p.license_number
ORDER BY games DESC, total_pts DESC;
```

### "Mi lett volna ha" — negyedenkénti elemzés
```sql
-- Ha a meccs az 1. negyed végén befejeződne:
SELECT m.match_id, m.match_date,
       qs.score_a as q1_a, qs.score_b as q1_b,
       m.score_a as final_a, m.score_b as final_b,
       CASE WHEN qs.score_a > qs.score_b THEN 'W'
            WHEN qs.score_a < qs.score_b THEN 'L' ELSE 'D' END as q1_result
FROM matches m
JOIN quarter_scores qs ON qs.match_id = m.match_id AND qs.quarter = '1';
```

### Liga pontkirályok
```sql
SELECT license_number, name,
       COUNT(*) as games,
       SUM(points) as total,
       ROUND(1.0 * SUM(points) / COUNT(*), 1) as ppg
FROM player_game_stats
WHERE points > 0
GROUP BY license_number
HAVING games >= 5
ORDER BY ppg DESC
LIMIT 20;
```

## Pipeline architektúra (extract_scoresheet.py)

```
PDF → PyMuPDF karakter-kinyerés
  → Template detekció (TYPE1/TYPE2)
  → extract_match_info()          → matches tábla
  → extract_referees()            → referees tábla
  → extract_officials()           → officials tábla
  → extract_players()             → players tábla
     ├─ Overflow szűrés (y-line grouping)
     ├─ Soronkénti név-assembly
     └─ Digit szűrés
  → extract_personal_fouls()      → personal_fouls tábla
  → extract_team_fouls()          → team_fouls tábla
  → extract_timeouts()            → timeouts tábla
  → extract_quarter_scores()      → quarter_scores tábla
  → extract_running_score()       → running_score tábla
     └─ Boundary correction pass (stray chars reallocation)
  → compute_scoring_events()      → scoring_events tábla
     └─ Stateful walk: color→quarter, circled→3PT, continuation FT
  → insert_scoring_events()
  → reconcile_jersey_numbers()    → scoring_events jersey fix
  → compute_player_game_stats()   → player_game_stats tábla
     └─ JOIN on license_number (jersey fallback)
```

## Ismert limitációk / Következő lépések

1. **~2.5% SE hiba** — A running score grid szélén csonkított számjegyek néha nem párosíthatók vissza. Javítható a COL_BOUNDS finomhangolásával vagy OCR-alapú fallback-kel.
2. **Hosszabbítás (OT)** — A kód kezeli, de kevés OT meccs volt a tesztelésben.
3. **Más bajnokságok** — A rendszer elvileg bármely MKOSZ bajnokságra működik (NB1, U20, stb.), de csak NB2-re volt tesztelve. Más bajnokságok más PDF template-et használhatnak.
4. **README.md elavult** — Egyetlen meccsre vonatkozik, a teljes pipeline-t ez a CLAUDE.md dokumentálja.
