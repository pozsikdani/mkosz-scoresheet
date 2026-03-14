# Kosárlabda & MKOSZ tudásbázis

> Play by Play projekt előkészítés — domain knowledge összefoglaló

## Kosárlabda alapok (FIBA szabályok, MKOSZ kontextus)

### Pontozás
- **2FG (2-point field goal)**: Íven belüli kosár — 2 pont
- **3FG (3-point field goal)**: Íven kívüli kosár — 3 pont
- **FT (free throw)**: Büntetődobás — 1 pont
- **Continuation FT**: Kosár + fault → a sikeres kosár pontjai + büntetődobás(ok)
- Missed FT: 0 pont, de a kísérlet számít (ft_attempted)

### Mérkőzés felépítés
- 4 negyed (quarter): Q1, Q2, Q3, Q4 — egyenként 10 perc (FIBA)
- Félidő: Q1-Q2 = első félidő, Q3-Q4 = második félidő
- Hosszabbítás (overtime/OT): 5 perc, korlátlan számú

### Faultok
- **Personal foul**: Egyéni fault, max 5/meccs/játékos → kizárás
- **Team foul**: Csapat-faultok negyedenként, 4 felett büntetődobás jár
- **Fault típusok**:
  - `defensive` — védekezési fault
  - `offensive` — támadó fault / charging
- **Fault kategóriák** (speciális):
  - `T` — Technikai fault (technikai szabálytalanság)
  - `U` — Sportszerűtlen fault (szándékos/flagráns)
  - `B` — Durva fault 1. fokozat
  - `C` — Durva fault 2. fokozat / edzői technikai
  - `D` — Kizáró fault (disqualifying)
  - `NULL` — Normál személyi fault (nincs speciális kategória)

### Játékos szerepek
- `player` — Mezőnyjátékos
- `captain` — Csapatkapitány (PDF-ben "(KAP)" jelöléssel)
- `coach` — Vezetőedző
- `assistant_coach` — Másodedző
- `starter` — Kezdő ötös tagja (1/0)
- `entry_quarter` — Melyik negyedben lépett pályára (1-4)

### Box score statisztikák (meccsenkénti egyéni)
- `points` — Összes szerzett pont
- `fg2_made` — Sikeres 2 pontos dobások
- `fg3_made` — Sikeres 3 pontos dobások
- `ft_made` — Sikeres büntetődobások
- `ft_attempted` — Összes büntetődobás kísérlet (made + missed)
- `personal_fouls` — Személyi faultok száma

### Scoring run
- Egymást követő kosarak, ahol az ellenfél nem szerez pontot
- Pl. "12-0 run" = 12 pontot szereztünk válasz nélkül
- Számítás: window function-nel `opp_run_id` csoportosítás, GROUP BY + SUM(points)

### Azonosítók
- **license_number (igazolásszám)**: MKOSZ regisztrációs szám — AZ EGYETLEN MEGBÍZHATÓ EGYEDI JÁTÉKOS-AZONOSÍTÓ
- Egy játékos különböző mezszámot viselhet különböző meccseken
- Két játékosnak lehet ugyanaz a neve
- A scoring events és player stats JOIN-ok `license_number`-t használnak

---

## MKOSZ szervezeti struktúra

### Liga hierarchia
```
NB1 — Legfelső liga (nem ez a projekt fókusza)
NB2 — Második osztály, regionális csoportok:
  ├── hun3ki  — NB2 Kiemelt (playoff/rájátszás, 90 meccs)
  ├── hun3koa — NB2 Közép A (72 meccs)
  ├── hun3kob — NB2 Közép B (72 meccs)
  ├── hun3k   — NB2 Kelet (72 meccs)
  └── hun3n   — NB2 Nyugat (72 meccs)
```

### Szezon kódok
- Formátum: `x{YYYY}{YY}` — pl. `x2526` = 2025/2026-os szezon
- `x2425` = 2024/2025

### Match ID formátum
- `{PREFIX}-{SORSZÁM}` — pl. `F2KB-0011`
- Prefix → bajnokság:

| Prefix | Bajnokság |
|--------|-----------|
| `F2KI` | NB2 Kiemelt |
| `F2KA` | NB2 Közép A |
| `F2KB` | NB2 Közép B |
| `F2KE` | NB2 Kelet |
| `F2NY` | NB2 Nyugat |

### Csapat azonosítók (MKOSZ team_id)
- A schedule/menetrend oldalakon a csapatokra `team_id`-vel hivatkoznak
- Pl. KÖZGÁZ B = `9239`, KÖZGÁZ A = `9219`

---

## MKOSZ URL-ek felépítése

### Bajnokság műsor (menetrend) oldal
```
https://mkosz.hu/bajnoksag-musor/{season}/{competition}/
```
Pl: `https://mkosz.hu/bajnoksag-musor/x2526/hun3kob/`

### Csapat-specifikus menetrend
```
https://mkosz.hu/bajnoksag-musor/{season}/{competition}/phase/0/csapat/{team_id}
```
Pl: `https://mkosz.hu/bajnoksag-musor/x2526/hun3k/phase/0/csapat/9239`

- Statikus HTML oldal (nem JavaScript-alapú), `<table class='box-table responsive'>` struktúra
- Regex-szel parse-olható, csapatnevek a `title` attribútumból
- Game ID-k kinyerhetők: `{competition}_(\d+)` regex pattern a linkekből

### PDF jegyzőkönyv letöltés
```
https://hunbasketimg.webpont.com/pdf/{season}/{competition}_{game_id}.pdf
```
Pl: `https://hunbasketimg.webpont.com/pdf/x2526/hun3kob_125843.pdf`

- A `game_id` a menetrend oldalról kinyerhető (a meccs linkjében szerepel)
- 404 = a PDF még nem elérhető (jövőbeli meccs)

### Paraméterek összefoglaló

| Paraméter | Formátum | Példa |
|-----------|----------|-------|
| `{season}` | `x{YYYY}{YY}` | `x2526` |
| `{competition}` | MKOSZ bajnokság kód | `hun3k`, `hun3kob` |
| `{team_id}` | Numerikus MKOSZ csapat ID | `9239` |
| `{game_id}` | Numerikus meccs azonosító | `125843` |

---

## PDF jegyzőkönyv struktúra (rövid összefoglaló)

### Tartalom
- Meccs metaadatok (csapatok, helyszín, dátum, időpont)
- Játékos roster (név, igazolásszám, mezszám, starter jelölés)
- Edzők (vezetőedző, másodedző)
- Játékvezetők, jegyző, időmérő
- Személyi faultok (5 slot/játékos: perc, negyed, típus, kategória)
- Csapat-faultok negyedenként
- Időkérések
- Negyedenkénti pontszámok
- **Running score grid** — a Play by Play forrása

### Running score grid
- 42 sor × 30 oszlop, 3 periódusra osztva (1. félidő, 2. félidő, hosszabbítás)
- 6 ismétlődő oszlopcsoport: Team A mez, Team A pontszám, Perc, Team B mez, Team B pontszám
- Szín-kódolás: piros=Q1, fekete=Q2, zöld=Q3, kék=Q4
- Bekarikázott mezszám = 3 pontos dobás
- `-` a pontszám oszlopban = kihagyott büntetődobás
- A negyedváltás a perc oszlop színéből állapítható meg

### Template variánsok
- **TYPE1** (standard): a legtöbb meccs
- **TYPE2** (korai variáns): eltérő y-offsetek
- **TYPE3** (VMG DSE hazai): kisebb sortávolság (24.31 vs 26.05 px), eltérő footer pozíció
- Detekció: match_id "F" karakter y-pozíciója + grid kezdő y-pozíció kombináció

### Ismert problémák
- 7 képes PDF (Nyugat, Kandó SC hazai): az egész oldal raszterkép, nincs szöveg
- Mezszám csonkítás: a running score gridben a tízes számjegy néha a cellahatáron kívül esik (pl. 17 → 7)
- Continuation FT: a mezszám hiányzik, az előző kosárnál használt mezszámot kell alkalmazni
