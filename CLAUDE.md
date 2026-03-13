# MKOSZ Scoresheet Extractor — Project Documentation

> Ez a fájl azért készült, hogy egy új Claude session (vagy bárki más) teljes kontextust kapjon a projektről.
> Utolsó frissítés: 2026-03-13.

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
├── generate_dashboards.py   # Játékos + csapat dashboard generátor (Chart.js HTML)
├── dashboards/              # KÖZGÁZ B generált dashboardok (GitHub Pages)
│   ├── index.html           # Áttekintő oldal (csapat kártya + játékos lista)
│   ├── csapat.html          # Csapat statisztikák dashboard
│   └── *.html               # 18 egyéni játékos dashboard
├── dashboards-a/            # KÖZGÁZ A generált dashboardok (GitHub Pages)
│   ├── index.html
│   ├── csapat.html
│   └── *.html               # 18 egyéni játékos dashboard
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
- Három template létezik: TYPE1 (`off_body=0`), TYPE2 (`off_body=-20`), TYPE3 (`off_body=5, row_height=24.31`)
- TYPE3 (VMG DSE hazai meccsek, Közép A): eltérő y-offsetek — header feljebb, grid lejjebb, footer jóval feljebb
- TYPE3 saját `row_height=24.31` (vs. 26.05) — kisebb sortávolság, nélküle sorok összekeverednek
- TYPE3 saját `off_footer=-103` — az eredmény és záradék eltérő y-pozícióban
- A detekció: match_id "F" karakter y-pozíció + grid-start y-pozíció kombináció
- `COL_BOUNDS` — a running score grid oszlophatárai, néhol -4px korrekcióval

## Pontossági metrikák (2025-26 szezon, 369 meccs)

| Csoport | Meccs | SE (scoring events) |
|---------|------:|:---:|
| Kiemelt | 90 | 90/90 **(100%)** |
| Közép A | 72 | 70/72 **(97.2%)** |
| Közép B | 72 | 72/72 **(100%)** |
| Kelet | 71 | 71/71 **(100%)** |
| Nyugat | 63 | 63/63 **(100%)** |
| **Összesen** | **368** | **366/368 (99.5%)** |

**7 képes PDF** (Nyugat, Óbudai Egyetem Kandó SC hazai meccsek): a jegyzőkönyvet egyetlen raszterképként exportálták (1400×2000px), nem tartalmaz kinyerhető szöveget. Érintett csapatok: Kandó SC (7 meccs hiányzik) + mind a 7 ellenfele (1-1 vendég meccs hiányzik).

**2 TYPE3 scoring eltérés** (F2KA-0095: -6, F2KA-0163: -2/-2): a forrás PDF running score grid hiányos (a végső pontok nem szerepelnek a gridben). A meccs-eredmény (`matches.score_a/b`) korrekt, csak a `scoring_events` granularitás érintett.

Korábbi javítások:
- COL_BOUNDS A*-2/M* határ +3px jobbra tolása (3 jegyű eredmények befogadása)
- `_try_repair_score()` safety net: csonkított/felfújt eredményértékek javítása
- TYPE3 template support (8 VMG DSE hazai meccs)

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

### Scoring run keresés (egy csapat leghosszabb pontozási sorozata válasz nélkül)

A "run" = egymást követő made kosarak, ahol az ellenfél nem szerez pontot.

**Logika:** A `scoring_events` táblában (csak `made=1` sorok) minden ellenfél-kosárnál új run kezdődik. A window function `SUM(CASE WHEN is_opponent THEN 1 ELSE 0 END) OVER (ORDER BY event_seq)` ad egy `opp_run_id`-t; a csapat egymást követő kosárai azonos `opp_run_id`-val rendelkeznek → GROUP BY és SUM(points).

**FONTOS:** A run a `scoring_events` sorrendjéből jön, NEM az azt megelőző kosárból. A run első eleme az ellenfél utolsó pontja UTÁNI első csapat-kosár. Gyakori hiba: a run elé bevenni egy korábbi kosarat, ami még az ellenfél utolsó pontja előtt történt.

```sql
-- Paraméterek: TEAM_PATTERN = csapatnév LIKE minta, COMP_PREFIX = match_id prefix (pl. F2KE)
WITH team_games AS (
    SELECT m.match_id, m.match_date,
           CASE WHEN m.team_a LIKE '%TEAM_PATTERN%' THEN 'A' ELSE 'B' END as t_team
    FROM matches m
    WHERE m.match_id LIKE 'COMP_PREFIX%'
      AND (m.team_a LIKE '%TEAM_PATTERN%' OR m.team_b LIKE '%TEAM_PATTERN%')
),
made_events AS (
    SELECT se.match_id, se.event_seq, se.quarter, se.points,
           tg.match_date, tg.t_team,
           CASE WHEN se.team = tg.t_team THEN 1 ELSE 0 END as is_team,
           CASE WHEN tg.t_team = 'A' THEN se.score_a ELSE se.score_b END as t_score,
           CASE WHEN tg.t_team = 'A' THEN se.score_b ELSE se.score_a END as opp_score
    FROM scoring_events se
    JOIN team_games tg ON se.match_id = tg.match_id
    WHERE se.made = 1
),
with_run_id AS (
    SELECT *,
           SUM(CASE WHEN is_team = 0 THEN 1 ELSE 0 END) OVER (
               PARTITION BY match_id ORDER BY event_seq
           ) as opp_run_id
    FROM made_events
)
SELECT match_id, match_date, opp_run_id,
       MIN(quarter) as start_q, MAX(quarter) as end_q,
       SUM(points) as run_points,
       COUNT(*) as baskets,
       MIN(t_score) - (SELECT points FROM with_run_id w2
           WHERE w2.match_id = r.match_id AND w2.event_seq = MIN(r.event_seq)
       ) as score_before,
       MAX(t_score) as score_after,
       MIN(opp_score) as opp_frozen
FROM with_run_id r
WHERE is_team = 1
GROUP BY match_id, opp_run_id
HAVING run_points >= 8
ORDER BY run_points DESC
LIMIT 10;
```

A run lebontásához (ki dobta a pontokat):
```sql
-- A fenti lekérdezés egy run-jának részletei (match_id + opp_run_id alapján)
-- Szűrd a with_run_id CTE-t: WHERE is_team = 1 AND match_id = ? AND opp_run_id = ?
-- JOIN players ON license_number a pontos névért
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
  → Template detekció (TYPE1/TYPE2/TYPE3)
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

## Dashboard generátor (generate_dashboards.py)

Interaktív HTML dashboardokat generál Chart.js-sel, GitHub Pages-en hostolva.

### Használat
```bash
python3 generate_dashboards.py all           # Mindkét csapat
python3 generate_dashboards.py kozgaz-b      # Csak KÖZGÁZ B
python3 generate_dashboards.py kozgaz-a      # Csak KÖZGÁZ A
```

### Csapat konfiguráció (TEAMS dict)
| Kulcs | team_pattern | comp_prefix | out_dir |
|-------|-------------|-------------|---------|
| `kozgaz-b` | `%KÖZGÁZ%DSK/B%` | `F2KE%` | `dashboards/` |
| `kozgaz-a` | `%KÖZGÁZ%DSK/A%` | `F2KB%` | `dashboards-a/` |

Új csapat hozzáadása: TEAMS dict bővítése + `python3 generate_dashboards.py <key>`.

### Generált fájlok csapatonként
- **`csapat.html`** — Csapat dashboard: W-L mérleg, negyedenkénti átlagok, pontmegoszlás (2FG/3FG/FT), forgatókönyvek (félidő/3Q vezet/hátrányban), top 5 saját + kapott scoring run, meccsnapló, fun facts
- **`index.html`** — Áttekintő: kiemelt csapat kártya + játékos lista pontátlag szerint
- **`{slug}.html`** — Játékos dashboard: pontszerzés trend, dobásmegoszlás, negyedenkénti teljesítmény, ellenfél-elemzés, meccsnapló, erősségek/gyengeségek

### GitHub Pages
- URL: `https://pozsikdani.github.io/mkosz-scoresheet/dashboards/` (B) és `dashboards-a/` (A)
- Google Sites beágyazás: `<iframe src="..." width="100%" height="800"></iframe>`

### Fontos implementációs részletek
- **Shot classification**: A `player_game_stats` és a csapat dashboard a `points` delta alapján osztályoz (points=3→3FG, points=2→2FG, points=1→FT), NEM a `shot_type` oszlop alapján. A `shot_type` oszlop néha pontatlan (pl. continuation FT-k 3FG-ként jelölve).
- **`_team_like()` pattern**: Ha a comp_prefix-ben csak egy KÖZGÁZ csapat szerepel, a broad pattern (`%KÖZGÁZ%`) elég; ha kettő is lenne, a specifikus pattern kell (`%KÖZGÁZ%DSK/B%`).
- **Scoring run logika**: Window function-nel `opp_run_id`-t számol, a run az ellenfél utolsó pontja UTÁN kezdődik (lásd fentebb a Scoring run fejezetet).

## Ismert limitációk / Következő lépések

1. **7 képes PDF (Nyugat, Kandó SC hazai)** — Az egész oldal egyetlen raszterképként van exportálva, PyMuPDF nem tud szöveget kinyerni. OCR-rel feldolgozható lenne. Érintett: Kandó SC (7 meccs) + 7 ellenfél (1-1 meccs).
2. **2 TYPE3 hiányos grid** — F2KA-0095 és F2KA-0163 running score gridje nem tartalmazza az utolsó pontokat. A meccs-eredmény korrekt, csak a scoring_events részletesség érintett.
3. **Hosszabbítás (OT)** — A kód kezeli, de kevés OT meccs volt a tesztelésben.
4. **Más bajnokságok** — A rendszer elvileg bármely MKOSZ bajnokságra működik (NB1, U20, stb.), de csak NB2-re volt tesztelve. Más bajnokságok más PDF template-et használhatnak.
5. **README.md elavult** — Egyetlen meccsre vonatkozik, a teljes pipeline-t ez a CLAUDE.md dokumentálja.
