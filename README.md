# MKOSZ Scoresheet Extractor

Extracts all structured data from an MKOSZ (Magyar Kosárlabdázók Országos Szövetsége) basketball scoresheet PDF into a SQLite database with 9 tables.

## Source

| Field | Value |
|---|---|
| Match | **BKG-PRIMA AKADÉMIA DEBRECEN** vs **BKG-VERESEGYHÁZ** |
| Match ID | F2KE-0183 |
| Date | 2026-03-08 17:00 |
| Venue | G4 FITNESS |
| Final score | A: **84** – B: **75** |

The source PDF is included as `hun3k_125657.pdf`.

## Database Schema

The SQLite database (`folyamatos_eredmeny.sqlite`) contains 9 tables:

### `match_info`

Match metadata (1 row).

| Column | Type | Description |
|---|---|---|
| `match_id` | TEXT | Match identifier (e.g. "F2KE-0183") |
| `team_a` | TEXT | Home team name |
| `team_b` | TEXT | Away team name |
| `venue` | TEXT | Venue name |
| `match_date` | TEXT | Date (YYYY-MM-DD) |
| `match_time` | TEXT | Start time (HH:MM) |
| `score_a` | INTEGER | Final score team A |
| `score_b` | INTEGER | Final score team B |
| `winner` | TEXT | Winning team name |
| `closure_timestamp` | TEXT | Scoresheet closure timestamp |

### `referees`

| Column | Type | Description |
|---|---|---|
| `role` | TEXT | "I. Játékvezető" or "II. Játékvezető" |
| `name` | TEXT | Referee name (and city) |

### `officials`

Scoresheet officials (scorer, timekeeper, etc.).

| Column | Type | Description |
|---|---|---|
| `role` | TEXT | "Jegyző", "Időmérő", or "24\"-es időmérő" |
| `name` | TEXT | Official name |

### `players`

Player rosters for both teams, including coaches.

| Column | Type | Description |
|---|---|---|
| `team` | TEXT | "A" or "B" |
| `license_number` | TEXT | MKOSZ license number |
| `name` | TEXT | Player/coach name |
| `jersey_number` | INTEGER | Jersey number (NULL for coaches) |
| `role` | TEXT | "player", "captain", "coach", or "assistant_coach" |
| `starter` | INTEGER | 1 = starting five (circled X), 0 = substitute |
| `entry_quarter` | INTEGER | Quarter of entry (1-4), determined by X marker color |

### `personal_fouls`

Individual fouls per player.

| Column | Type | Description |
|---|---|---|
| `team` | TEXT | "A" or "B" |
| `jersey_number` | INTEGER | Player jersey number |
| `foul_number` | INTEGER | Sequential foul number (1-5) |
| `minute` | TEXT | Minute when foul was committed (1-10) |
| `quarter` | INTEGER | Quarter (1-4), determined by color |

### `team_fouls`

Team foul count per quarter (max 4 boxes on scoresheet).

| Column | Type | Description |
|---|---|---|
| `team` | TEXT | "A" or "B" |
| `quarter` | INTEGER | Quarter (1-4) |
| `foul_count` | INTEGER | Number of X marks (0-4) |

### `timeouts`

Timeout events.

| Column | Type | Description |
|---|---|---|
| `team` | TEXT | "A" or "B" |
| `quarter` | INTEGER | Quarter (1-4) |
| `minute` | TEXT | Minute when timeout was called |

### `quarter_scores`

Score per quarter.

| Column | Type | Description |
|---|---|---|
| `quarter` | TEXT | "1", "2", "3", "4", or "Hosszabbítás" |
| `score_a` | INTEGER | Team A score for that quarter |
| `score_b` | INTEGER | Team B score for that quarter |

### `running_score`

The "Folyamatos Eredmény" table — every cell of the running score grid.

| Column | Type | Description |
|---|---|---|
| `header` | TEXT | Period: `Első félidő`, `Második félidő`, or `Hosszabbítás` |
| `column_name` | TEXT | Grid column (see below) |
| `color` | TEXT | `red`, `black`, `green`, or `blue` |
| `circled` | INTEGER | `1` if the value is circled, `0` otherwise |
| `row_number` | INTEGER | 1-based row index |
| `character` | TEXT | The cell value — a number or `-` |

#### Column naming — 3 szintű hierarchia

**1. szint — Félidő (`header`):** `Első félidő` (Q1+Q2), `Második félidő` (Q3+Q4), `Hosszabbítás`

**2. szint — Oszlopcsoport:** A (team A), M (minute), B (team B) — kétszer ismétlődve

**3. szint — Egyedi oszlop (`column_name`):**

| `column_name` | Jelentés |
|---|---|
| `A_-1` | A csapat — mezszám |
| `A_-2` | A csapat — ponteredmény (futó összeg) |
| `M_` | Megkezdett perc |
| `B_-1` | B csapat — mezszám |
| `B_-2` | B csapat — ponteredmény (futó összeg) |

Az 1. ismétlés: `A1-1`, `A1-2`, `M1`, `B1-1`, `B1-2`; a 2. ismétlés: `A2-1`, `A2-2`, `M2`, `B2-1`, `B2-2`.

#### Circled entries

| Oszlop típus | `circled = 1` jelentése |
|---|---|
| Mezszám (`A_-1`, `B_-1`) | **Hárompontos kosár** |
| Ponteredmény (`A_-2`, `B_-2`) | **Negyed-/félidővég eredmény** |

#### Color legend

| Szín | Negyed | Hex |
|---|---|---|
| red | 1. negyed | `#FF0000` |
| black | 2. negyed | `#000000` |
| green | 3. negyed | `#088008` |
| blue | 4. negyed | `#0000FF` |

## Usage

### Prerequisites

```bash
pip install PyMuPDF
```

### Run the extractor

```bash
python extract_scoresheet.py
```

This reads `hun3k_125657.pdf` (must be in the same directory) and writes/overwrites `folyamatos_eredmeny.sqlite` with all 9 tables.

### Query the database

```bash
sqlite3 folyamatos_eredmeny.sqlite
```

#### Example queries

**Match info:**

```sql
SELECT team_a, team_b, score_a, score_b, venue, match_date FROM match_info;
```

**Starting five:**

```sql
SELECT team, jersey_number, name FROM players WHERE starter = 1 ORDER BY team;
```

**Three-pointers:**

```sql
SELECT header, column_name, character AS mezszám, row_number, color
FROM running_score
WHERE circled = 1
  AND column_name IN ('A1-1','A2-1','B1-1','B2-1')
ORDER BY header, row_number;
```

**Player fouls summary:**

```sql
SELECT p.team, p.name, p.jersey_number, COUNT(f.id) AS total_fouls
FROM players p
LEFT JOIN personal_fouls f ON p.team = f.team AND p.jersey_number = f.jersey_number
WHERE p.role IN ('player', 'captain')
GROUP BY p.team, p.jersey_number
ORDER BY total_fouls DESC;
```

**Scoring types with COALESCE(LAG, 0):**

```sql
WITH scores AS (
    SELECT header, column_name, row_number,
           CAST(character AS INTEGER) AS score, color
    FROM running_score
    WHERE column_name IN ('A1-2','A2-2')
      AND character != '-'
),
diffs AS (
    SELECT *,
        score - COALESCE(LAG(score) OVER (ORDER BY
            CASE WHEN header='Első félidő' THEN 1 ELSE 2 END,
            CASE WHEN color='red' THEN 1 WHEN color='black' THEN 2
                 WHEN color='green' THEN 3 ELSE 4 END,
            CASE WHEN column_name LIKE '%1-%' THEN 0 ELSE 1 END,
            row_number
        ), 0) AS diff
    FROM scores
)
SELECT * FROM diffs WHERE diff > 0;
```

### Summary (this match)

- **231** running score records
- **23** players (14 A + 9 B, including coaches)
- **32** personal fouls (18 A + 14 B)
- **8** timeouts (3 A + 5 B)
- Quarter scores: 22-18, 20-24, 25-13, 17-20 → **84-75**
