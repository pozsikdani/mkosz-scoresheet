# Changelog

## 2026-11-23

### Fixed
- **A név-ablak levágta a nevek elejét** (`NAME_X_MIN` 95 → 74): a TYPE3 sablon
  MINDEN nevének (141/141) és 22 TYPE2-sornak hiányzott az első betűje
  („AGY GERGŐ" a „NAGY GERGŐ" helyett). 163 név állt helyre, 0 ürült ki.
- **A magányos „-" (kihagyott büntető) átlógónak látszott**: a Hosszabbítás
  oszlopcsoportban a kötőjel átlépte az „átlógott" küszöböt, és a kiolvasó a
  következő csoport mezszám-oszlopába vitte — ahol amúgy is eldobja. Ettől nem
  csak a kihagyott büntető veszett el, hanem a rá következő folytatólagos
  büntetők is rossz játékoshoz kerültek. +100 kihagyott büntető, 50 sor került
  közelebb a hivatalos adathoz, 0 romlott.
- **A perc balra csúszása a pontszám-cellába** (`MINUTE_SPILL_GAP`): ahol az oszlophatár
  a pontszám és a perc közé esik, a perc eddig elveszett (a pontszám jó maradt, mert a
  `_try_repair_score()` levágta). 61 új perc, 206 javított `0`→`10`, 0 elveszett.
- **A hosszabbítás a 4. negyedbe került** (`OVERTIME_QUARTER`): a negyed a tinta
  színéből jött, a hosszabbítás viszont ugyanazzal a kékkel megy, mint a 4. negyed —
  most a „Hosszabbítás" fejléc dönt. 451 esemény, 31 meccs.

Mindkettő Andris jelzésére. A box score 25 264 sorából 0 változott.

## 2026-11-22

### Fixed
- **A pontszám levágott első számjegye** (`_reclaim_leading_digit()`): folytatólagos
  büntetőnél a folyamatos eredmény tízes számjegye a mezszám-cellába esik, és mivel
  ott egyedül áll, a régi határkorrekció nem vette észre — a sor elveszett, a pontjait
  a következő sor nyelte le. 50 játékos-sor javult (27 a hivatalos box score-hoz, 18 a
  play-by-play-hez mérve közelebb, 0 romlott).

## 2026-03-24

### Changed
- `.gitignore`: removed `*.sqlite` so pre-computed databases can be committed to git.

### Data
- Regenerated `scoresheet.sqlite` from 378 PDFs: 372 matches, 7,262 player game stats, 35,174 scoring events.

## 2026-03-21

### Fixed
- **CI pipeline**: robusztus `player_stats` kezelés — nem szakad meg ha a tábla nem létezik.

### Data
- `scoresheet.sqlite`: NB2 összes csoport (Kelet, Nyugat, Közép A/B, Kiemelt) + Budapest regionális bajnokságok.
- 372 scoresheet feldolgozva.
