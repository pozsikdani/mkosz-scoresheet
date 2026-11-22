# Changelog

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
