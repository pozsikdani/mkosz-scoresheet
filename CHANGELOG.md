# Changelog

## 2026-11-25

### Fixed
- **A B-mezszám vezető jegye a perc-cellába csúszott** (Case 5): a perc-cella
  ott végződik, ahol a B-mezszám oszlopa kezdődik, és a mezszám mezője
  jobbra zárt — az első jegye egyetlen betűlépésre áll az utolsótól. Néhány
  PDF-en az egész B-blokk 2-5 px-rel balra van rajzolva, és a kétjegyű
  mezszám TÍZES jegye átcsúszik a perc-cellába. Ami ott marad, az lesz a perc:
  valódi perc mellett „12", „31", „45", „52", „61", „81" (perc + mezszám-tízes
  — **az adatbázis MINDEN lehetetlen perc-értéke innen jött**), perc nélküli
  sorban pedig a mezszám tízese egyedül, hihető de hamis kis percként.
  A Case 4(b) tükörképe, ezért a döntés PDF-enként kalibrált: egy
  (félidő, csoport) valódi percei egy x-slotban állnak, az elcsúszott
  mezszám-jegy ~11 px-rel jobbra.
  Visszafelé lépő perc **62 → 7**, a 10-nél nagyobb (fizikailag lehetetlen)
  perc-érték **7 → 0**. A maradék 7 visszalépés közül 4 jogos: a
  „Hosszabbítás" fül MINDEN ráadást tart, és a második ráadásban a perc
  újraindul 1-ről. A másik 3 jegyzői elírás (köztük a 7 darab „0", amit
  szándékosan nem találunk ki).
  **44 játékos-sor változott 16 meccsen; független forráshoz (hivatalos MKOSZ
  meccsoldal, ill. play-by-play) mérve 43 KÖZELEBB — mind a 43 pontosan
  ráállt a hivatalos értékre —, 0 romlott**, 1 nem ellenőrizhető.
  Box score = hivatalos 2533 → 2538/2572; mezszám-változás 78 esemény, a
  névsor szerint 17 javult, 0 romlott; név 0, elveszett sor 0, esemény 115 743
  változatlan.

## 2026-11-24

### Fixed
- **A 10. perc szétesett az oszlophatáron** (`MINUTE_TENS_GAP`): a perc-oszlop
  14 px, a kétjegyű perc ~16 — a „10" tehát nem mindig fér bele, és az egyik
  jegye a szomszéd oszlopba esik. Két irányban: a tízes jegy BALRA a
  pontszám-cellába (a perc „0"-t olvas), vagy az egyes jegy JOBBRA a B-mezszám
  oszlopába (a perc „1"-et olvas). A bizonyíték a betűlépés: egy SZÁM
  szomszédos jegyei 4,9-8,2 px-re állnak (medián 7,9), a pontszám és a perc
  legalább 9,3-ra, a perc és a B-mezszám legalább 12-re — plusz a
  lehetetlenség: „0" sosem perc, mezszám pedig csak a 0 és a 00 kezdődik
  nullával, és azok 15-21 px-re állnak, sosem 7,9-re.
  Perc `0` 321 → 7, perc `10` 3463 → **4483** (+1020), visszafelé lépő perc
  **398 → 62**. A play-by-play-hez mért durva perc-hiba (|eltérés| ≥ 2)
  355 → 220. 11 játékos-sor változott, **mind a 11 közelebb** a független
  forráshoz (8 pontosan ráállt), **0 romlott**; box score 2579/2618
  változatlan, név 0, elveszett sor 0.

## 2026-11-23

### Fixed
- **TYPE3 csapatrész-eltolás és felirat-horgonyzott edző-sáv**: a TYPE3 lap
  lefelé haladva egyre jobban elcsúszik, ezért a két csapatrésznek saját
  eltolása van (`off_players_a/b`); az edző-sáv pedig a nyomtatott
  `EDZŐ`/`SEGÉDEDZŐ` felirathoz horgonyzódik, nem fix koordinátához. Box score
  2435/2490 → 2452/2490 (17 javult, 0 romlott), segédedző 578 → 755.
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
