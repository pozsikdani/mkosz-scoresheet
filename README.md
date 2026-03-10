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
| `circled` | INTEGER | `1` if the value is circled, `0` otherwise (see [Circled entries](#circled-entries)) |
| `row_number` | INTEGER | 1-based row index (topmost row = 1) |
| `character` | TEXT | The cell value — a number (up to 3 digits) or `-` |

### Column naming — 3 szintű hierarchia

A Folyamatos Eredmény tábla oszlopai 3 szintű hierarchiát követnek:

**1. szint — Félidő (`header`):**

| Érték | Leírás |
|---|---|
| `Első félidő` | 1. és 2. negyed |
| `Második félidő` | 3. és 4. negyed |
| `Hosszabbítás` | Hosszabbítás (ha van) |

**2. szint — Oszlopcsoport:**

Minden félidő alatt háromféle oszlopcsoport található, **kétszer ismétlődve** (1. és 2. ismétlés):

| Oszlopcsoport | Leírás |
|---|---|
| `A` | Az **A csapat** adatai (mezszám + ponteredmény) |
| `M` | **Megkezdett perc** |
| `B` | A **B csapat** adatai (mezszám + ponteredmény) |

**3. szint — Egyedi oszlop (`column_name`):**

A `column_name` kódolja az oszlopcsoportot és az ismétlést is. Az `_` helyén `1` az első, `2` a második ismétlés:

| `column_name` | Oszlopcsoport | Jelentés |
|---|---|---|
| `A_-1` | A | A csapat — mezszám |
| `A_-2` | A | A csapat — ponteredmény (futó összeg) |
| `M_` | M | Megkezdett perc |
| `B_-1` | B | B csapat — mezszám |
| `B_-2` | B | B csapat — ponteredmény (futó összeg) |

Tehát az 1. ismétlés oszlopai: `A1-1`, `A1-2`, `M1`, `B1-1`, `B1-2`; a 2. ismétlés oszlopai: `A2-1`, `A2-2`, `M2`, `B2-1`, `B2-2`.

Egy cella egyedileg azonosítható a `(header, column_name, row_number)` hármassal.

### Circled entries

A `circled = 1` érték két különböző dolgot jelent, attól függően melyik oszlopban van:

| Oszlop típus | Jelentés |
|---|---|
| Mezszám (`A_-1`, `B_-1`) | **Hárompontos kosár** — a játékos hárompontost dobott |
| Ponteredmény (`A_-2`, `B_-2`) | **Negyed-/félidővég** — az adott negyed vagy mérkőzés végeredménye |

#### Hárompontosok lekérdezése

```sql
SELECT header, column_name, character AS mezszám, row_number, color
FROM running_score
WHERE circled = 1
  AND column_name IN ('A1-1','A2-1','B1-1','B2-1')
ORDER BY header, row_number;
```

#### Negyedvégi eredmények lekérdezése

```sql
SELECT header, column_name, character AS ponteredmény, row_number, color
FROM running_score
WHERE circled = 1
  AND column_name IN ('A1-2','A2-2','B1-2','B2-2')
ORDER BY header, row_number;
```

### Color legend

A négy szín a negyedeket jelöli:

| Szín | Negyed | Hex a PDF-ben |
|---|---|---|
| red | 1. negyed | `#FF0000` |
| black | 2. negyed | `#000000` |
| green | 3. negyed | `#088008` |
| blue | 4. negyed | `#0000FF` |

### Summary (this match)

- **231** total records
- **42** rows
- Headers: Első félidő (123), Második félidő (108), Hosszabbítás (0 — no overtime)
- **15** circled entries (7 hárompontos + 8 negyedvégi eredmény)

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

**Hárompontosok (bekarikázott mezszámok):**

```sql
SELECT row_number, header, column_name, character AS mezszám, color
FROM running_score
WHERE circled = 1
  AND column_name IN ('A1-1','A2-1','B1-1','B2-1')
ORDER BY header, row_number;
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
