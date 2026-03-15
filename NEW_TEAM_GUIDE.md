# Új csapat hozzáadása a kozgazkosar.hu-hoz

> Lépésről lépésre útmutató új Közgáz csapat felvételéhez a weboldalra.

## Előfeltételek

1. A csapat meccseihez tartozó **PDF jegyzőkönyvek** letöltve és feldolgozva legyenek az `nb2_full.sqlite`-ban
2. Ismerd a csapat **MKOSZ bajnokság kódját** és **team ID-ját** (a menetrend oldalról)
3. Ismerd a csapat **pontos nevét** ahogy az adatbázisban (`matches.team_a/team_b`) szerepel

## Szükséges MKOSZ adatok megtalálása

### Bajnokság kód (`mkosz_comp`)
Az MKOSZ menetrend URL-ből:
```
https://mkosz.hu/bajnoksag-musor/x2526/{COMP}/
```
Pl. `hun3k` = NB2 Kelet, `hun3kob` = NB2 Közép B

### Team ID (`mkosz_team_id`)
A csapat-specifikus menetrend URL-ből:
```
https://mkosz.hu/bajnoksag-musor/x2526/{COMP}/phase/0/csapat/{TEAM_ID}
```
A menüben kattints a csapatra és nézd a böngésző címsorát.

### Match ID prefix (`comp_prefix`)
Az adatbázis `matches.match_id` oszlopából. Konvenció:

| Prefix | Bajnokság |
|--------|-----------|
| `F2KI` | NB2 Kiemelt |
| `F2KA` | NB2 Közép A |
| `F2KB` | NB2 Közép B |
| `F2KE` | NB2 Kelet |
| `F2NY` | NB2 Nyugat |

Más bajnokságoknál (NB1B, MEFOB, stb.) ellenőrizd a letöltött PDF-ekből.

---

## 1. lépés: `TEAMS` dict bővítése

**Fájl**: `generate_dashboards.py`, ~20. sor

```python
TEAMS = {
    "kozgaz-b": { ... },
    "kozgaz-a": { ... },
    # ↓ ÚJ CSAPAT ↓
    "leftoverz": {
        "team_pattern": "%LEFTOVERZ%",          # Specifikus SQL LIKE pattern
        "team_pattern_broad": "%LEFTOVERZ%",    # Tágabb LIKE pattern (ha egyedi, ugyanaz)
        "comp_prefix": "F2KE%",                 # Match ID prefix (bajnokság)
        "team_name": "LEFTOVERZ KSE",           # Teljes név az adatbázisból
        "team_short": "Leftoverz",              # Rövid név (nav bar, homepage)
        "group_name": "NB2 Kelet",              # Liga/csoport neve megjelenítéshez
        "out_dir": "dashboards-leftoverz",      # Kimeneti könyvtár (repo root-hoz relatív)
        "mkosz_season": "x2526",                # MKOSZ szezon kód
        "mkosz_comp": "hun3k",                  # MKOSZ bajnokság kód
        "mkosz_team_id": "12345",               # MKOSZ csapat ID (menetrend URL-ből)
    },
}
```

### Mire figyelj:
- **`team_pattern`**: SQL LIKE minta. Ha a csapat neve egyedi a bajnokságban, elég a tágabb is (pl. `%LEFTOVERZ%`). Ha két Közgáz csapat van ugyanabban a bajnokságban, kell a specifikus (pl. `%KÖZGÁZ%DSK/B%`).
- **`team_pattern_broad`**: Automatikusan tesztelve: ha pontosan 1 csapat felel meg a bajnokságban, ez lesz használva. Ha 2+, a `team_pattern` lesz.
- **`out_dir`**: Egyedi könyvtárnév. Ez jelenik meg az URL-ben is: `www.kozgazkosar.hu/{out_dir}/`

---

## 2. lépés: `NAV_TEAMS` bővítése

**Fájl**: `generate_dashboards.py`, ~48. sor

```python
NAV_TEAMS = [
    {"key": "kozgaz-b", "label": "Öregek NB2", "href": "dashboards"},
    {"key": "kozgaz-a", "label": "Fiatalok NB2", "href": "dashboards-a"},
    # Leftoverz jelenleg placeholder → aktiválás:
    {"key": "leftoverz", "label": "Leftoverz", "href": "dashboards-leftoverz"},
]
```

### Mire figyelj:
- A `"href"` értéke meg kell egyezzen a TEAMS-beli `"out_dir"` értékkel
- A `"key"` értéke meg kell egyezzen a TEAMS-beli kulccsal
- Ha a `key` szerepel a TEAMS dict-ben, aktív linkként jelenik meg; ha nem, disabled placeholder lesz
- A sorrend határozza meg a nav bar sorrendjét

---

## 3. lépés: Leftoverz placeholder eltávolítása

**Fájl**: `generate_dashboards.py`, ~1947. sor — a `_nav_html()` függvényben:

```python
if t["key"] == "leftoverz":  # ← ezt a feltételt kell módosítani vagy törölni
```

Ha a Leftoverz csapat most valódi tartalmat kap, töröld ezt az `if` ágat, hogy rendes linkként jelenjen meg. Ha más csapatot is placeholder-nek akarsz, adj hozzá az `if`-hez.

---

## 4. lépés: `CALENDAR_SHORT` dict bővítése (ha kell)

**Fájl**: `generate_dashboards.py`, ~114. sor

Ha az új csapat **más bajnokságban** játszik, új ellenfelek lehetnek akik nincsenek benne a short name dict-ben. Adj hozzá:

```python
CALENDAR_SHORT = {
    # ... meglévő nevek ...
    "ÚJ ELLENFÉL TELJES NEVE": "Rövid",
    "MÁSIK ELLENFÉL": "Más.ell",
}
```

A naptárcellákban ez a rövid név jelenik meg. Ha egy ellenfél nincs a dict-ben, az első szó lesz használva (max 10 karakter).

---

## 5. lépés: Edzéslátogatás (opcionális)

Ha az új csapatnak is van edzéslátogatás spreadsheetje:

### a) Google Sheets CSV URL
**Fájl**: `generate_dashboards.py`, ~55. sor

Hozz létre egy új URL konstanst:
```python
ATTENDANCE_SHEET_URL_LEFTOVERZ = "https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GID}"
```

### b) Név mapping
Hozz létre egy új `ATTENDANCE_NAME_MAP_LEFTOVERZ` dict-et (spreadsheet becenév → DB formális név).

### c) Feltételes fetch a `generate_team()`-ben
**~2356. sor**: Jelenleg így néz ki:
```python
att_data = fetch_training_attendance() if team_key == "kozgaz-b" else {}
```
Bővítsd:
```python
if team_key == "kozgaz-b":
    att_data = fetch_training_attendance()
elif team_key == "leftoverz":
    att_data = fetch_training_attendance_leftoverz()
else:
    att_data = {}
```

### d) `update_attendance.py` bővítése
Ha automatikus frissítés is kell, a `update_attendance.py`-t is ki kell bővíteni az új csapat HTML fájljaira.

---

## 6. lépés: PDF-ek letöltése és feldolgozása

```bash
# 1. PDF-ek letöltése (ha új bajnokság)
python3 download_scoresheets.py x2526 {MKOSZ_COMP} ./pdfs/

# 2. Feldolgozás
python3 extract_scoresheet.py ./pdfs/ --db nb2_full.sqlite

# 3. Ellenőrzés: a csapat megjelenik-e az adatbázisban
sqlite3 nb2_full.sqlite "SELECT DISTINCT team_a FROM matches WHERE match_id LIKE '{PREFIX}%' AND team_a LIKE '%CSAPATNÉV%'"
```

---

## 7. lépés: Site generálás és tesztelés

```bash
# Csak az új csapat
python3 generate_dashboards.py leftoverz

# Vagy a teljes site (összes csapat + főoldal)
python3 generate_dashboards.py site

# Lokális tesztelés
python3 -m http.server 8765
# Böngészőben: http://localhost:8765/dashboards-leftoverz/
```

---

## 8. lépés: Push

```bash
git add dashboards-leftoverz/ index.html generate_dashboards.py
git commit -m "feat: Leftoverz csapat hozzáadása"
git push
```

---

## Összefoglaló: módosítandó helyek

| # | Fájl | Sor (kb.) | Mit kell csinálni |
|---|------|-----------|-------------------|
| 1 | `generate_dashboards.py` | ~20 | `TEAMS` dict: új csapat config |
| 2 | `generate_dashboards.py` | ~48 | `NAV_TEAMS`: új menüpont |
| 3 | `generate_dashboards.py` | ~1947 | `_nav_html()`: Leftoverz `if` eltávolítása |
| 4 | `generate_dashboards.py` | ~114 | `CALENDAR_SHORT`: új ellenfelek (ha kell) |
| 5 | `generate_dashboards.py` | ~2356 | Edzéslátogatás feltétel (ha kell) |
| 6 | `update_attendance.py` | — | Új csapat attendance (ha kell) |

---

## Meglévő csapatok referencia

| Kulcs | Csapatnév | Bajnokság | Prefix | MKOSZ comp | Team ID | Output dir |
|-------|-----------|-----------|--------|------------|---------|------------|
| `kozgaz-b` | KÖZGÁZ SC ÉS DSK/B | NB2 Kelet | `F2KE` | `hun3k` | `9239` | `dashboards/` |
| `kozgaz-a` | KÖZGÁZ SC ÉS DSK/A | NB2 Közép B | `F2KB` | `hun3kob` | `9219` | `dashboards-a/` |

---

## Tippek

- **Más bajnokság** (pl. NB1B, MEFOB): Először a `download_scoresheets.py`-val töltsd le a PDF-eket és dolgozd fel. Ellenőrizd, hogy a PDF template (TYPE1/TYPE2/TYPE3) felismerése működik-e.
- **Más szezon**: Módosítsd az `mkosz_season` értékét (pl. `x2627` a 2026/27-es szezonhoz).
- **Tesztelés**: Az `_team_like()` függvény automatikusan kezeli a pattern logikát. Ha a csapat neve egyedi a bajnokságban, a broad pattern lesz használva.
- **Hazai/Vendég nézet**: A csapat dashboardon automatikusan elérhető (toggle gombok), nincs extra konfiguráció.
