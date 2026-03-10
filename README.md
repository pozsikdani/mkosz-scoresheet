# MKOSZ Scoresheet — Running Score Extractor

Extracts the **"Folyamatos Eredmény"** (Running Score) table from an MKOSZ (Magyar Kosárlabdázók Országos Szövetsége) basketball scoresheet PDF and stores every cell as a structured record in a SQLite database.

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

The SQLite database (`folyamatos_eredmeny.sqlite`) contains a single table:

### `running_score`

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key (auto-increment) |
| `header` | TEXT | Period: `Első félidő`, `Második félidő`, or `Hosszabbítás` |
| `column_name` | TEXT | Grid column (see below) |
| `color` | TEXT | `red`, `black`, `green`, or `blue` |
| `circled` | INTEGER | `1` if the number is circled, `0` otherwise |
| `row_number` | INTEGER | 1-based row index (topmost row = 1) |
| `character` | TEXT | The cell value — a number (up to 3 digits) or `-` |

### Column naming

Each period header spans **two sub-groups** of five columns. The naming convention is:

| Sub-group | Columns |
|---|---|
| 1 (left) | `A1-1`, `A1-2`, `M1`, `B1-1`, `B1-2` |
| 2 (right) | `A2-1`, `A2-2`, `M2`, `B2-1`, `B2-2` |

A unique cell is identified by the combination of `(header, column_name, row_number)`.

### Color legend

The four colors used in the table:

| Color | Hex in PDF |
|---|---|
| red | `#FF0000` |
| black | `#000000` |
| green | `#088008` |
| blue | `#0000FF` |

### Summary (this match)

- **231** total records
- **42** rows
- Headers: Első félidő (123), Második félidő (108), Hosszabbítás (0 — no overtime)
- **15** circled entries (mark quarter/game final scores)

## Usage

### Prerequisites

```bash
pip install PyMuPDF
```

### Run the extractor

```bash
python extract_running_score.py
```

This reads `hun3k_125657.pdf` (must be in the same directory) and writes/overwrites `folyamatos_eredmeny.sqlite`.

### Query the database

```bash
sqlite3 folyamatos_eredmeny.sqlite
```

#### Example queries

**All circled entries (quarter/game final scores):**

```sql
SELECT row_number, header, column_name, character, color
FROM running_score
WHERE circled = 1
ORDER BY row_number;
```

**Count records by color:**

```sql
SELECT color, COUNT(*) AS cnt
FROM running_score
GROUP BY color
ORDER BY cnt DESC;
```

**All entries in a specific column:**

```sql
SELECT row_number, character, color, circled
FROM running_score
WHERE header = 'Első félidő' AND column_name = 'A1-2'
ORDER BY row_number;
```

**Reconstruct a full row:**

```sql
SELECT header, column_name, character, color, circled
FROM running_score
WHERE row_number = 1
ORDER BY header, column_name;
```
