# MKOSZ Scoresheet Extractor — Project Documentation

> Ez a fájl azért készült, hogy egy új Claude session (vagy bárki más) teljes kontextust kapjon a projektről.
> Utolsó frissítés: 2026-03-14.

## Mi ez a projekt?

Automatikus feldolgozó rendszer, ami a **Magyar Kosárlabda Szövetség (MKOSZ)** digitális jegyzőkönyv PDF-jeiből strukturált SQLite adatbázist készít. A PDF-ekből karakterszintű pozíció-alapú kinyeréssel (PyMuPDF, NEM OCR) dolgozik.

A rendszer képes egy teljes bajnokság összes jegyzőkönyvét automatikusan letölteni az MKOSZ weboldaláról és feldolgozni.

**Tulajdonos kontextus**: A projekt tulajdonosa a **KÖZGÁZ SC ÉS DSK** kosárlabda csapat tagja/edzője. Két csapat érintett:
- **KÖZGÁZ A** (NB2 Közép B csoport) — a magasabb szintű csapat
- **KÖZGÁZ B** (NB2 Kelet csoport) — a második csapat

A dashboardok és elemzések elsősorban e két csapatra készülnek, a csapat weboldalán jelennek meg.

## Repo & hosting

- **GitHub**: https://github.com/pozsikdani/mkosz-scoresheet
- **GitHub Pages** (aktív): https://pozsikdani.github.io/mkosz-scoresheet/
- **Custom domain**: https://www.kozgazkosar.hu/ (CNAME fájl a repo gyökerében)
- **gh CLI**: `/opt/homebrew/bin/gh` (nem a default úton)
- **Nyelv**: Python 3, HTML/JS (Chart.js), SQLite

## Fájlstruktúra

```
mkosz-scoresheet/
├── extract_scoresheet.py    # Fő feldolgozó script (~1900 sor)
├── download_scoresheets.py  # Automatikus PDF letöltő
├── generate_dashboards.py   # Site + dashboard + naptár generátor (~2200 sor)
├── update_attendance.py     # Edzéslátogatás frissítő (HTML in-place, SQLite nélkül)
├── CNAME                    # Custom domain: www.kozgazkosar.hu
├── index.html               # Klub főoldal (csapat kártyák, közelgő meccsek, eredmények)
├── README.md                # Eredeti dokumentáció (elavult, egyetlen meccsre vonatkozik)
├── CLAUDE.md                # ← EZ A FÁJL — teljes projekt kontextus
├── .github/
│   └── workflows/
│       └── update-attendance.yml  # GitHub Actions: napi edzéslátogatás frissítés
├── .gitignore               # *.sqlite, pdfs/
├── pdfs/                    # Letöltött PDF-ek (gitignore-ban, regenerálható)
│   ├── hun3ki_*.pdf         # NB2 Kiemelt (90 meccs)
│   ├── hun3koa_*.pdf        # NB2 Közép A (72 meccs)
│   ├── hun3kob_*.pdf        # NB2 Közép B (72 meccs)
│   ├── hun3k_*.pdf          # NB2 Kelet (72 meccs)
│   └── hun3n_*.pdf          # NB2 Nyugat (72 meccs)
├── dashboards/              # KÖZGÁZ B generált dashboardok (GitHub Pages)
│   ├── index.html           # Áttekintő oldal (játékos lista mezszámokkal)
│   ├── csapat.html          # Csapat statisztikák dashboard
│   ├── naptar.html          # Meccsnaptár (havi nézet, MKOSZ-ról scrape-elve)
│   └── *.html               # 18 egyéni játékos dashboard
├── dashboards-a/            # KÖZGÁZ A generált dashboardok (GitHub Pages)
│   ├── index.html
│   ├── csapat.html
│   ├── naptar.html
│   └── *.html               # 18 egyéni játékos dashboard
├── kadocsa_dashboard.html   # Eredeti önálló Kadocsa Márton dashboard (legacy, superseded by dashboards/)
├── scoresheet.sqlite          # Teljes NB2 adatbázis (gitignore-ban, regenerálható)
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
python3 extract_scoresheet.py ./pdfs/ --db scoresheet.sqlite

# Vagy újrafeldolgozás (meglévő meccseket is felülírja):
python3 extract_scoresheet.py ./pdfs/ --db scoresheet.sqlite --force
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

### team_a = hazai, team_b = vendég
- `matches.team_a` mindig a **hazai** csapat, `team_b` a **vendég**
- `scoring_events.team` és `player_game_stats.team` értéke 'A' vagy 'B' — ehhez igazodik
- Amikor egy KÖZGÁZ meccs adatait nézzük: `CASE WHEN team_a LIKE '%KÖZGÁZ%' THEN 'A' ELSE 'B' END` adja a KÖZGÁZ team kódját

### match_id prefixek (bajnokság azonosítás)
| Prefix | Bajnokság |
|--------|-----------|
| `F2KI` | NB2 Kiemelt |
| `F2KA` | NB2 Közép A |
| `F2KB` | NB2 Közép B |
| `F2KE` | NB2 Kelet |
| `F2NY` | NB2 Nyugat |

A `match_id` formátum: `{prefix}-{sorszám}`, pl. `F2KB-0011`.

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

### A meccs kulcsa a PDF neve, nem a jegyzőkönyvszám (2026-11-19)

A `matches.match_id` a **forrás-PDF nevéből** jövő azonosító (`hun3k_141597`),
a jegyzőkönyvszám pedig a `sheet_number` oszlopban van (`F2KE-0021`).

**Miért:** a jegyzőkönyvszám szezononként újrakezdődik, tehát a 2025/26-os
`hun3k_125493.pdf` és a 2026/27-es `hun3k_141597.pdf` is `F2KE-0021` — a két
meccs felülírta egymást. Mérve 2026-11-19-én: 1402 sikeresen kiolvasott PDF-ből
csak 1248 meccs volt az adatbázisban, 55 ütköző azonosítóval. A migráció és egy
teljes újrakiolvasás után 1301 meccs, úgy, hogy egy idei meccs sem veszett el.

A PDF-ből jövő azonosító ráadásul **ugyanaz, amit a `mkosz-stats` importálója
használ** (`extract_gamecode_from_pdf`), tehát a két oldal kulcsa egybeesik.
A fogyasztók (mkosz-stats, mkosz-dashboard, mkosz-scout) átlátszó kulcsként
használják, a `match_id` alakját egyik sem elemzi.

**Meglévő adatbázis átállítása:**
```bash
python3 extract_scoresheet.py --migrate-ids --dry-run --db scoresheet.sqlite  # próbamenet
python3 extract_scoresheet.py --migrate-ids --db scoresheet.sqlite
```
A migráció minden táblában átírja a kulcsot, a végén `PRAGMA foreign_key_check`
fut, és hibát dob, ha sérült hivatkozás maradt. Az ellenőrzést a művelet
idejére kikapcsolja (a `defer_foreign_keys` a Python implicit tranzakciójában
nem él), ezért a záró ellenőrzés **nem elhagyható**.

A felülírt meccsek visszanyeréséhez nem kell `--force`: a „már feldolgozva"
vizsgálat a `source_pdf`-re néz, tehát amelyik PDF sora elveszett, azt a
következő futás magától újra feldolgozza.

### Sorok a licencszámokhoz igazítva (2026-11-19)

A csapat játékos-sorait **nem fix y-ablakokból** vesszük, hanem a ténylegesen
megtalált licencszám-sorokhoz igazítjuk (`player_row_bands`). 2026 októberétől
az MKOSZ PDF-jeinek egy részén a sorköz 24,5 helyett 26,8 px, és az első sor
licencszáma az ablak tetejére vagy fölé csúszik — emiatt kimaradt az első sor
(egy Közgáz-meccsen 13 pont és a kezdő-jelölés), kimaradt a 12. sor, és a
faultokat a sor fix +12 px-es toldása miatt a kód kétszer számolta.

Mérve mindkét elrendezésen, a licencsorhoz képest: **egysoros név +1,8**,
mezszám és X 0…+2,2, a sor saját faultjai 0 (az alsó indexek +8…+12), a szomszéd
sorok ±24-27 px-re. Ezért a sáv a licencsor fölött 4 px-szel kezdődik és a
következő licencsorig tart; a faultok ebből jönnek, így az alsó indexek
(U/T/B/C/D) benne vannak, a következő sor faultjai nem.

**A név kivétel, és ez egy drágán tanult lecke:** a **tördelt** (két sorba törő)
név első sora a licencsor FÖLÖTT van (−4,5), a második sora és a „(KAP)" alatta
(+8,1). Ha a nevet a sávból olvassuk, a tördelt nevek egy sorral feljebb
csúsznak, és a régi „a sávtetőhöz közeli sorokat eldobjuk" szabály az előző sor
saját nevét dobja ki helyettük — a tavalyi anyagon ez 989 sor nevét rontotta
volna el. Ezért a név a licencsor körüli saját ablakból jön
(`NAME_ABOVE`/`NAME_BELOW` = ±13 px). Az eredeti mérésem csak egysoros neveket
nézett, és emiatt ez majdnem kiment: **a geometriát tördelt néven is meg kell
mérni.**

A csapatrész végét **nem koordináta zárja le**, hanem a sorok száma (max. 12) és
az egyenletes sorköz megtörése (`spacing * 1.6`). Egy korábbi változatban az
edző-sáv elé húzott határ levágta a 12. sort: az új sorköznél az pont
1306,8-nál van, a határ 1310-nél — **kevesebb mint egy pixelen múlt**. Ha nincs
egyetlen licencsor sem, a kód a régi fix ablakokra esik vissza
(`_fixed_row_bands`).

### Mérési csapdák (2026-11-19)

1. **Az éles `scoresheet.sqlite` NEM alapvonal egy kód-diffhez.** A sorait
   hónapok alatt, különböző kódverziókkal írta a CI, így a diff minden azóta
   történt változást mutat, nem csak a mostanit. Alapvonalhoz a *módosítatlan*
   kódot kell lefuttatni ugyanazokon a PDF-eken:
   `git show origin/main:extract_scoresheet.py > /tmp/base.py && python3 /tmp/base.py pdfs --db /tmp/base.sqlite`.
2. **A `match_id` nem elég kulcs az összehasonlításhoz.** A jegyzőkönyvszám
   szezononként újrakezdődik (a 2025/26-os `hun2a_135735.pdf` és a 2026/27-es
   `hun2a_123447.pdf` is `F1PF-0011`), tehát két különböző meccs írja felül
   egymást. Összehasonlításnál a `matches.source_pdf` a kulcs. Ez magában az
   adatbázisban is valódi hiba — külön javítandó.
3. **A legjobb egyetlen mérőszám** erre a kiolvasóra: hány csapat-félidőben
   egyezik a játékosok pontösszege a hivatalos eredménnyel (`matches.score_a/b`).
   Ez önellenőrző, és egy rossz javítás azonnal lerontja.
4. **A metrikakészlet addig hiányos, amíg van mező, amit egyik szám sem fog meg.**
   A box score licencszám szerint kapcsol, ezért a NEVEK elromlását egyetlen
   fenti mérőszám sem mutatta — a sorok száma, a pontok és a faultok mind
   rendben voltak, miközben 989 név elcsúszott egy sorral. Összehasonlításkor a
   `players.name` is kerüljön bele (`source_pdf` + `team` + `license_number`
   kulcson), külön bontva: üressé vált / kiegészült / más névre váltott.

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

Korábbi javítások (kronológiai sorrendben):
1. COL_BOUNDS A*-2/M* határ +3px jobbra tolása (3 jegyű eredmények befogadása)
2. `_try_repair_score()` safety net: csonkított/felfújt eredményértékek javítása
3. TYPE3 template support (8 VMG DSE hazai meccs)
4. **Shot classification fix** (`compute_player_game_stats()`, ~1722. sor): `shot_type` oszlop helyett `points` delta alapú osztályozás. A `shot_type='3FG'` néha 1 vagy 2 pontos eseményeknél is megjelent (continuation FT-k). Javítás: `points=3→fg3, points=2→fg2, points=1→ft_made, points∈{0,1}→ft_attempted`. Liga-szinten 2721 eseményt érintett.
5. **Game log query fix**: `get_game_log()` a 6. paraméterben `COMP_PREFIX`-et kap (nem `TEAM_PATTERN`-t) a `match_id LIKE ?` feltételhez — különben üres eredmény
6. **A pontszám levágott első számjegye** (`_reclaim_leading_digit()`, 2026-11-22). A
   folyamatos eredmény tízes (vagy százas) számjegye pont az oszlophatáron áll, és
   néha a mezszám-cellába esik. Ahol a jegyző mezszámot is írt, a
   `extract_running_score()` határkorrekciója szétszedi a kettőt — de
   **folytatólagos büntetőnél a mezszám-cella üres**, így a beszorult számjegy
   egyedül marad, és semmi nem jelzi, hogy odatévedt. Ilyenkor a sor elveszett, a
   pontjait pedig a következő sor nyelte le: `hun3k_141651`-ben a „74"-ből mezszám 7
   + eredmény 4 lett, ettől Látos elvesztett egy büntetőt, Somogyi pedig kapott egy
   nem létező triplát (a csapatösszeg 105 maradt, ezért a box-score metrika vak volt rá).
   **A pozíció nem dönti el**: a felmérés szerint valódi egyjegyű mezszám is áll a
   cellahatártól 4 px-re, beszorult számjegy is 1 px-re, és hogy melyik van közelebb,
   PDF-enként változik. Ezért a bizonyíték maga az eredmény: a számjegyet csak akkor
   vesszük vissza, ha az eredmény önmagában lehetetlen (visszafelé lépne), a
   visszaillesztett viszont pont 1-3 ponttal nő. Mérve mind az 1092 PDF-en: 50
   megváltozott játékos-sor, ebből 27 a hivatalos MKOSZ box score-hoz, 18 a
   play-by-play-hez **közelebb került, 0 romlott**; név nem sérült.
   A `_try_repair_score()` csak HÁTULRA fűz számjegyet, ezt a hibát nem fogta meg.
   A nyers `running_score` tábla a PDF szerinti (hibás) bontást őrzi — nincs fogyasztója.
7. **A perc balra csúszása és a hosszabbítás negyede** (2026-11-23, Andris jelzésére).
   (a) A perc számjegyei csak ~15 px-re állnak a pontszámtól, és néhány PDF-en az
   oszlophatár kevesebb mint egy pixellel a kettő KÖZÉ esik (`hun3k_141651`: a perc
   x=729,9-nél, az `M1` oszlop 730-nál kezdődik). Ilyenkor a cella „451"-et ad
   (45 pont + 1 perc), amit a `_try_repair_score()` levág: a pontszám jó lesz, a perc
   elvész — ezért nem jött ki a 2. félidő percének nagy része. **Oszlophatárt tolni
   itt TILOS**: mérve 1364 PDF-en, a 2. félidei percek 98,7%-a a helyén van, a
   határ eltolása a ritka hibát cserélné gyakorira. A szabály ezért a RÉSHEZ kötött,
   mint a 6. pontban: a pontszám saját számjegyei 6-8 px-re állnak egymástól, a
   pontszám és a perc 15-17 px-re (`MINUTE_SPILL_GAP = 12.0`). Kétjegyű percnél csak
   a tízes jegy csúszik be, ezért a levált rész ELÉ kerül a perc-cella tartalmának —
   ez a „10 helyett 0" eset.
   (b) A hosszabbítás a saját, „Hosszabbítás" fejlécű oszlopcsoportjába kerül, de
   UGYANAZZAL a kék tintával, mint a 4. negyed, a negyed pedig a színből jött — ezért
   a hosszabbítás kosarai a 4. negyedbe kerültek. A fejléc a megkülönböztető jel
   (`OVERTIME_QUARTER = 5`); a csoport nem periódus, csak helykitöltés (42 sor/hasáb).
   Mérve 1364 PDF-en, módosítatlan alapvonalhoz képest: **a box score 25 264 sorából
   0 változott** (pont, név, 3FG, büntető), negyed csak 4→5 irányba (451 esemény,
   31 meccs), perc 206-szor `0`→`10`, 61 új perc, **0 elveszett**, és a visszafelé
   lépő percek 625-ről 393-ra estek.

   **Ami ebből MEGMARADT:** 398 visszafelé lépő perc — ezt a 11. pont zárta le.

8. **A magányos „-" (kihagyott büntető) átlógónak látszott** (2026-11-23, Andris
   jelzésére). A Case 1 szabály a `B*-2` cellát átlógónak tekinti, ha minden
   karaktere 15 px-nél messzebb kezdődik a bal széltől, és a következő
   oszlopcsoport `A*-1` mezszám-oszlopába viszi. Ez a küszöb olyan oszlopokra van
   hangolva, ahol a tartalom 2-6 px-nél kezdődik — a **Hosszabbítás** csoportban
   viszont az egész oszlop jobbra tolódik (kétjegyű pontszám 12,3-nál, magányos
   „-" 18,1-nél), így a kötőjel átlépi a 15-öt, a pontszámok nem.
   A `hun3k_125647`-en ez mind a 3 Közgáz-hosszabbításbeli kihagyott büntetőt
   elvitte: Bartus 14/14 lett 14/15 helyett, Bencze 0/0 a 0/2 helyett.
   **Az érv, ami eldönti:** a célhely egy MEZSZÁM-oszlop, ahol a
   `compute_scoring_events()` a „-"-t amúgy is eldobja (az ott „ugyanaz a játékos"
   jelentésű), tehát az áthelyezés nem adhat hozzá semmit, csak veszíthet. Ezért
   a szabály csak akkor fut, ha a cellában van legalább egy SZÁMJEGY.
   Nem csak a kihagyott büntető tért vissza: a „-" eldobásával a teljes sor
   kimaradt, így a rá következő folytatólagos büntetők az ELŐZŐ mezszámra kerültek
   (`hun2b_124209`: 3 büntető a 79-esre a 11-es helyett). Mérve 1364 PDF-en:
   +100 kihagyott büntető, 75 megváltozott játékos-sor, ebből **50 került
   közelebb** a független forráshoz (MKOSZ meccsoldal, ahol nincs: play-by-play),
   **0 romlott**, 16 azonos távolságra maradt, 8 nem volt ellenőrizhető.
   1 sor eldönthetetlen (`hun3koa_125799`), mert ott a név eleve csonka
   („AGY GERGŐ" a „NAGY GERGŐ" helyett) — az a TYPE3 név-ablak hibája, külön
   javítandó.
9. **A név-ablak levágta a nevek elejét** (2026-11-23). A név `x=[95, 275)`-ből
   jött, de a név nem mindenhol ugyanott kezdődik. Mérve mind az 1364 PDF-en,
   sablononként (`NAME_X_MIN` kommentjében is):

   | | licenc jobb széle (max) | név kezdete (min) | levágott sor |
   |---|---:|---:|---:|
   | TYPE1 | 68,4 | 104,4 | 0 / 22 008 |
   | TYPE2 | 69,3 | **78,7** | 22 / 2 873 |
   | TYPE3 | 60,3 | **88,5** | **141 / 141** |

   A két tartomány között mindenhol tiszta rés van, ezért a határ a közepére,
   **74**-re került. A licencszám így sem tud beszivárogni: a névből a
   számjegyeket amúgy is kiszűrjük, a licenc pedig csupa számjegy.
   Mérve: **163 név állt helyre**, ebből 161 tiszta előtag-visszanyerés
   (1-5 karakter), 2 egyéb — az egyiknél a beszivárgott „(KAP)" töredék is
   eltűnt, a másik tördelt név, ahol MINDKÉT sor elvesztette az első betűjét.
   0 név ürült ki, 0 játékos-sor veszett el a közös meccseken, a box score
   változatlan (a név nem befolyásolja a pontot).

   **A TYPE3 offset-hibáit a 10. pont zárta le.**
10. **TYPE3 csapatrész-eltolás és felirat-horgonyzott edző-sáv** (2026-11-23).
   Két külön hiba, két külön mechanizmussal.

   **(a) A csapatrész.** A TYPE3 nem egyszerű eltolás: a lap lefelé haladva
   egyre jobban elcsúszik, ezért a két csapatrésznek SAJÁT eltolása kell.
   Mérve mind a 12 TYPE3 PDF-en, a TYPE1/TYPE2-nél érvényes
   „`y_start` = első licencsor − 17" konvencióval:

   | | A első licencsora | B első licencsora |
   |---|---:|---:|
   | TYPE1 | 446,7 | 1050,6 |
   | TYPE2 | 412,1 | 1014,5 |
   | TYPE3 | **383,5** | **946,5** |

   A közös `off_body=+5` miatt a B keresőablak 1013-nál kezdődött, a névsor
   viszont 946,5-nél — ezért maradt csonka. Innen a `off_players_a=-64` és
   `off_players_b=-104`, csak a TYPE3 template-en.

   **(b) Az edző-sáv.** Fix y-ablakokból jött, eltolással — és két okból is
   melléfogott: TYPE3-on a B ablaka (1363-1390) a hivatalos személyzetet fogta
   meg az edző helyett (innen jöttek a „DEMETER TAMÁS (TÁRNOK)" sorok), a
   SEGÉDEDZŐ ablaka pedig MINDEN sablonon a felirat alatt kezdődött (TYPE1-en a
   feliratok mediánja 764,1, az ablak 768-nál) — ezért volt 2428 edző mellett
   csak 578 segédedző.

   A megoldás ugyanaz az elv, mint a játékos-soroknál a licencszám: **horgony a
   nyomtatott feliratokhoz.** Az `EDZŐ` / `SEGÉDEDZŐ` felirat feketével ott van
   minden olvasható PDF-en, és mérve mind az 1364-en a kék NÉV pontosan a
   felirat sorában áll (eltérés 0,0). Ahol nincs felirat (képes PDF, 122 db),
   a kód a régi, eltolt ablakra esik vissza.

   Mérve, módosítatlan alapvonalhoz képest, az 1246 közös meccsen:

   | | |
   |---|---|
   | box score = hivatalos | 2435/2490 → **2452/2490** (17 javult, **0 romlott**) |
   | segédedző | 578 → **755** (+177) |
   | edző | 2428 → **2483** (+55) |
   | kapitány | 2465 → 2483 (+18) |
   | játékos | 22 613 → 22 661 (+48) |
   | **eltűnt játékos-sor** | **0** |

   A `hun3koa_125799` box score-ja 51-70-ről **58-90-re** javult, ami pontosan a
   hivatalos eredmény. Ott a B csapat „edzője" `MOLNÁR MÁTÉ (KAP)` — ez NEM
   hiba: játékos-edző, a kapitány játékos-licence 129804, az edző-soré 5300
   (négyjegyű, mint a többi edzőé).

11. **A 10. perc szétesett az oszlophatáron** (2026-11-24). Ez volt a 7. pontban
   nyitva maradt 398 visszafelé lépő perc valódi oka, és nem „kétféle hiba",
   hanem egy szerkezeti tény: **a perc-oszlop 14 px, a kétjegyű perc ~16**, tehát
   a „10" nem mindig fér bele, és az egyik jegye a szomszéd oszlopba esik. Két
   irányban, és mindkettő LEHETETLEN percet hagy maga után:

   | | a kiszökő jegy | ahova esik | a perc így | eset |
   |---|---|---|---:|---:|
   | (a) | tízes `1` | balra, `A*-2` (pontszám) | `0` | 1297 |
   | (b) | egyes `0` | jobbra, `B*-1` (B-mezszám) | `1` | 39 |

   **A bizonyíték a betűlépés.** Mérve mind az 1364 PDF-en: egy SZÁM szomszédos
   jegyei 4,9-8,2 px-re állnak egymástól (medián 7,9; 48 282 mérés), a pontszám
   és a perc viszont legalább 9,3-ra (23 405 mérés — és ezt a 9,3-at a három
   jegyű eredmények adják, a szokásos 15-17), a perc és a B-mezszám legalább
   12-re. Vagyis az oszlophatáron átnyúló, pontosan EGY betűlépésre álló
   számjegy ugyanannak a számnak a jegye. A két klaszter közt tiszta rés van,
   ezért a küszöb a közepére, **9,0**-ra került (`MINUTE_TENS_GAP`).

   **A lehetetlenség legalább ennyit számít.** „0" sosem perc, a perc sosem több
   10-nél, mezszám pedig csak a 0 és a 00 kezdődik nullával — és azok 15-21 px-re
   állnak a perctől, sosem 7,9-re. Geometria + lehetetlenség együtt dönt, külön
   egyik sem elég: a Hosszabbítás csoportban a jobbra tolódás miatt valódi
   pontszám-perc pár is 7,9-re áll (`hun2a_ply_134111`), ott viszont a perc
   érvényes, tehát a szabály nem indul el.

   **Miért nem fogta meg ezt a `MINUTE_SPILL_GAP` (7. pont)?** Az ugyanezt méri,
   de a pontszám-cellán BELÜL. Egy teljes perc 15-17 px-re áll a pontszámtól, egy
   magányos tízes jegy viszont csak 11,4-12,0-ra (a „10" szélesebb, ezért balra
   tolódik a középre zárásból) — pont a 12,0-as küszöb ALATT. A küszöb
   leszállítása rossz válasz lett volna: a szám-belső rések p99-e 11,8.
   A lone `1`-et pedig a `len(char_list) < 2` eleve kizárta.

   **Egy helyen hagytam szándékosan hibát:** ha a `B*-1` tartalma pontosan `0` és
   a sorban van B-pontszám, akkor a `0` lehet a 0-as mezszám is, és az elvétele a
   kosarat az ELŐZŐ mezszámra vinné. Geometriával ez nem szétválasztható, ezért
   az a 6 sor (1364 PDF-ből) marad. Perc-hibát vállalni jobb, mint dobót cserélni.

   Mérve, módosítatlan alapvonalhoz képest, 1310 közös meccsen:

   | | |
   |---|---|
   | perc `0` | 321 → **7** |
   | perc `10` | 3463 → **4483** (+1020) |
   | esemény perccel | 43 726 → 44 409 (+683) |
   | **visszafelé lépő perc** | **398 → 62** |
   | durva perc-hiba a play-by-play-hez (\|eltérés\| ≥ 2) | 355 → **220** |
   | box score = hivatalos | 2579/2618 → 2579/2618 |
   | megváltozott játékos-sor | 11 — **mind a 11 közelebb** a független forráshoz (8 pontosan ráállt), **0 romlott** |
   | név, elveszett sor | 0, 0 |

   A 11 megváltozott sor nem melléktermék, hanem nyereség: ahol a tízes jegy
   bent maradt a pontszám-cellában, ott a `_try_repair_score()` a SOR VÉGÉT
   vágta le, és ettől elcsúszott a dobó. `hun3k_141611`-ben Kis Levente 23 pont
   / 1 tripla volt 20 / 0 helyett, Plangár Máté 0 pont 2 helyett.
   **A box score ezekre vak volt**, mert a csapatösszeg nem változott (egy
   játékos kapott +1 triplát, egy másik vesztett egy büntetőt) — ugyanaz a
   csapda, mint a 6. pontnál, ezért kellett a play-by-play és az MKOSZ
   meccsoldal külön ellenőrzésnek.

   **Ami ebből MEGMARADT:** 62 visszafelé lépő perc, de már csak **20 meccsen**,
   szinte mind a 4. negyedben / hosszabbításban és a B oldalon — tehát a lap
   jobb szélén, ahol a sablon-csúszás a legnagyobb. Ez meccsenként csoportosul,
   vagyis PDF-szintű elrendezési eltérés, nem az itt javított szerkezeti ok.
   Mellette 7 lehetetlen perc-érték (12, 31, 45, 52, 61, 81), ahol a B-mezszám
   egy jegye a perc MÖGÉ került, és 7 megmaradt `0`.

   **Külön észrevétel, nem hiba:** a 115 743 eseményből **72 ezernek nincs perce
   (62%)**, és ez a forrás tulajdonsága — a jegyző negyedenként ~10 perc-jelet ír,
   nem soronként. Ha a perc minden eseményre kellene, az a jelet lefelé
   örökítő olvasás lenne (`minute` = a sor fölötti utolsó jel az adott
   negyedben), ami jelentés-változás, ezért nem csináltam meg.

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
python3 generate_dashboards.py site          # Teljes site: mindkét csapat + főoldal (alapértelmezett)
python3 generate_dashboards.py kozgaz-b      # Csak KÖZGÁZ B
python3 generate_dashboards.py kozgaz-a      # Csak KÖZGÁZ A
python3 generate_dashboards.py all           # Mindkét csapat (főoldal nélkül)
```

### Csapat konfiguráció (TEAMS dict)
| Kulcs | team_pattern | comp_prefix | out_dir | mkosz_comp | mkosz_team_id |
|-------|-------------|-------------|---------|------------|---------------|
| `kozgaz-b` | `%KÖZGÁZ%DSK/B%` | `F2KE%` | `dashboards/` | `hun3k` | `9239` |
| `kozgaz-a` | `%KÖZGÁZ%DSK/A%` | `F2KB%` | `dashboards-a/` | `hun3kob` | `9219` |

Minden csapatnak van `mkosz_season`, `mkosz_comp`, `mkosz_team_id` mezője a meccsnaptár scraping-hez.

Új csapat hozzáadása: TEAMS dict bővítése + `python3 generate_dashboards.py <key>`.

### Generált fájlok

**Klub főoldal** (`index.html` a repo gyökerében):
- Hero szekció ("KÖZGÁZ BASKETBALL")
- Csapat kártyák (W-L mérleg, következő meccs)
- Leftoverz placeholder (szürke, szaggatott keret)
- Közelgő meccsek (mindkét csapatból, dátum szerint)
- Legutóbbi eredmények (hazai csapat előre, szín: zöld/piros)

**Csapatonként** (`dashboards/` és `dashboards-a/`):
- **`index.html`** — Áttekintő: csapat stat kártya + naptár kártya + játékos lista mezszámokkal
- **`csapat.html`** — Csapat dashboard: W-L mérleg, negyedenkénti átlagok, pontmegoszlás (2FG/3FG/FT), forgatókönyvek (félidő/3Q vezet/hátrányban), top 5 saját (zöld) + kapott (piros) scoring run, meccsnapló, fun facts
- **`naptar.html`** — Meccsnaptár: havi naptár nézet, MKOSZ weboldalról scrape-elve. Lejátszott meccsek zöld (W) / piros (L) badge-dzsel és színes eredménnyel, jövőbeli meccsek szürke háttérrel. @ prefix idegenbeli meccsekhez.
- **`{slug}.html`** — Játékos dashboard: pontszerzés trend, dobásmegoszlás, negyedenkénti teljesítmény, ellenfél-elemzés, meccsnapló, erősségek/gyengeségek

**Navigáció minden oldalon**:
- Nav bar: Közgáz Basketball logo + Öregek NB2 / Fiatalok NB2 / Leftoverz linkek
- Vissza gomb: hierarchikus (homepage←team index←subpages)

### Weboldal linkek (kozgazkosar.hu)
| Oldal | URL |
|-------|-----|
| Főoldal | [www.kozgazkosar.hu](https://www.kozgazkosar.hu/) |
| Öregek NB2 | [www.kozgazkosar.hu/dashboards/](https://www.kozgazkosar.hu/dashboards/) |
| Fiatalok NB2 | [www.kozgazkosar.hu/dashboards-a/](https://www.kozgazkosar.hu/dashboards-a/) |

DNS: Websupport.hu-n 4× A record (185.199.108-111.153) + CNAME (www → pozsikdani.github.io).

### Frissítési pipeline
```bash
# Ha új meccsek kerültek az MKOSZ-re:
python3 download_scoresheets.py x2526 hun3k ./pdfs/         # Kelet (KÖZGÁZ B)
python3 download_scoresheets.py x2526 hun3kob ./pdfs/       # Közép B (KÖZGÁZ A)
python3 extract_scoresheet.py ./pdfs/ --db scoresheet.sqlite  # Feldolgozás
python3 generate_dashboards.py site                         # Teljes site újragenerálás (edzéslátogatás is frissül)
git add index.html dashboards/ dashboards-a/ && git commit && git push  # kozgazkosar.hu frissül

# Csak edzéslátogatás frissítés (SQLite nélkül, GitHub Actions is ezt futtatja):
python3 update_attendance.py
git add dashboards/ && git commit && git push
```

### Ütközés a napi CI-vel extractor-javítás után (2026-11-24)

Ha egy extractor-javítás után teljes `--force` újraolvasás megy, a napi CI
(`Napi import` / `Napi frissítés` / `Scoresheet frissítés`) közben feltolhatja
a saját automata commitját mind a három repóba, és a push elhasal. A három
repó NEM egyformán oldódik fel, mert a CI más-más okból „régi":

| repó | a CI commitja | feloldás |
|---|---|---|
| `mkosz-scoresheet` | **elavult** — a CI nem `--force`-ol, csak az új PDF-eket olvassa, a régi meccsek a javítás előtti értéket tartják | `git merge -s ours origin/main` — a helyi újraolvasás marad |
| `mkosz-stats` | **értékes** — benne van a CI aznapi friss play-by-play importja (nálunk nincs) | `git reset --hard origin/main`, majd újra `cli.py import scoresheet` + `cli.py resolve` a CI DB-jére |
| `mkosz-dashboard` | generált, a CI a régi stats DB-ből csinálta | `git reset --hard origin/main`, majd újra `generate_dashboards.py site` a végleges DB-ből |

Vagyis: a scoresheet-DB-nél a miénk nyer, a stats-DB-nél **egyiket sem lehet
eldobni** (a CI pbp-je + a mi scoresheet-importunk kell), a dashboard pedig
mindig a legvégén, a kész stats DB-ből generálódik újra. A döntés előtt
MINDIG hasonlítsd össze a két DB-t sor-szinten (`git show origin/main:<db>`
temp fájlba), ne a commit-idő alapján válassz.

### generate_dashboards.py architektúra
```
generate_site()                              — teljes site generálás (alapértelmezett)
  → generate_team(team_key) × minden csapat
  │   → _team_like()                         — broad vs specific LIKE pattern
  │   → get_roster()                         — roster lekérdezés (license, name, jersey, games, ppg)
  │   → fetch_training_attendance()          — Google Sheets CSV fetch (csak kozgaz-b)
  │   → Játékosonként:
  │   │   → get_game_log()                   — meccsenként stat
  │   │   → get_quarter_stats()              — negyedenkénti scoring_events
  │   │   → get_opponent_ppg()               — ellenfél elleni átlag
  │   │   → get_tech_unsport()               — technikai/sportszerűtlen faultok
  │   │   → generate_insights()              — erősségek/gyengeségek szöveges elemzés
  │   │   → generate_html()                  — egyéni HTML dashboard (+ back-link)
  │   → get_team_stats()                     — csapat szintű lekérdezések
  │   → generate_team_dashboard()            — csapat HTML dashboard (szemantikus színek)
  │   → scrape_schedule()                    — MKOSZ weboldalról menetrend scraping
  │   │   └─ fallback: get_calendar_data_db() — SQLite-ból ha scraping sikertelen
  │   → generate_calendar()                  — havi naptár HTML (lejátszott + jövőbeli meccsek)
  │   → generate_index()                     — áttekintő HTML (játékos grid mezszámokkal)
  │   → returns cal_data                     — naptár adatok a főoldalhoz
  → generate_homepage(team_summaries)        — klub főoldal (csapat kártyák, meccsek)

Navigáció:
  NAV_TEAMS config                           — menüpontok (Öregek/Fiatalok/Leftoverz)
  _nav_html(active_key, depth)               — nav bar HTML generátor
  NAV_CSS                                    — nav bar stílusok
```

### Meccsnaptár scraping (naptar.html)

A `scrape_schedule(cfg)` függvény közvetlenül az MKOSZ weboldalról húzza a menetrend adatokat:

**URL minta**: `https://mkosz.hu/bajnoksag-musor/{season}/{comp}/phase/0/csapat/{team_id}`

**Működés**:
- Az MKOSZ oldal statikus HTML-t ad (nem JS-alapú), `<table class='box-table responsive'>` struktúrában
- Regex-szel parse-ol: csapatnevek a `title` attribútumból, magyar dátum (`"2025. október 7."` → `2025-10-07`), időpont, eredmény (ha van), match_id (href-ből)
- Lejátszott meccsek: zöld/piros háttér + W/L badge + színes eredmény (zöld/piros)
- Jövőbeli meccsek: lila háttér, ellenfél + időpont, eredmény nélkül
- Ha a scraping sikertelen (hálózati hiba), SQLite fallback (`get_calendar_data_db()`)

**Magyar dátum parse**: `HU_MONTHS_PARSE` dict (`{"január":1, ..., "december":12}`)

**Ellenfél rövidítések**: `CALENDAR_SHORT` dict + `calendar_short_name()` függvény — rövid nevek a naptár cellákhoz (pl. "BKG-PRIMA AKADÉMIA DEBRECEN" → "Debrecen"). Away meccsekhez `@` prefix (pl. `@Debrecen`).

### Edzéslátogatás (Közgáz B only)

Az edzéslátogatás adatok automatikusan a Google Sheets-ből kerülnek betöltésre:

**Spreadsheet**: `1CY9OV_JY4C5uzTcA621zs0-rd5gPO7ELau5yvrSsA-0` (gid=`1405052111`)

**Működés**:
- `fetch_training_attendance()` — CSV export letöltés urllib-bel, csv.reader-rel parse
- CSV struktúra: C oszlop = játékos név (becenév), E oszlop = arány (pl. "26/34")
- `ATTENDANCE_NAME_MAP` dict: spreadsheet becenév → adatbázis formális név (pl. "Lénárt Zoli" → "LÉNÁRT ZOLTÁN")
- Pozsik Dániel (edző) kihagyva
- Közgáz A csapatnál nincs edzéslátogatás adat

**Megjelenítés**:
- Játékos dashboard fejléc: teal színű "Edzés" stat (pl. "26/34 (76%)")
- Index oldal: külön sor a meccs/PPG alatt: `🏋️ 26/34 (76%)`

**Automatikus frissítés** (GitHub Actions):
- `.github/workflows/update-attendance.yml` — naponta reggel 6:00 UTC-kor (8:00 magyar idő)
- `update_attendance.py` futtatása — regex-szel frissíti az edzéslátogatás értékeket a meglévő HTML-ekben
- SQLite nem szükséges hozzá (csak HTML fájlokat módosít)
- Kézi indítás: GitHub Actions → "Run workflow"
- Ha a Google Sheets elérhető: commit + push ha változott az adat
- Ha nem elérhető: nem módosít semmit

**Új játékos hozzáadása**: `ATTENDANCE_NAME_MAP` dict bővítése a `generate_dashboards.py`-ban (spreadsheet becenév → DB formális név).

### Fontos implementációs részletek
- **Shot classification**: A `player_game_stats` és a csapat dashboard a `points` delta alapján osztályoz (points=3→3FG, points=2→2FG, points=1→FT), NEM a `shot_type` oszlop alapján. A `shot_type` oszlop néha pontatlan (pl. continuation FT-k 3FG-ként jelölve).
- **`_team_like()` pattern**: Ha a comp_prefix-ben csak egy KÖZGÁZ csapat szerepel, a broad pattern (`%KÖZGÁZ%`) elég; ha kettő is lenne, a specifikus pattern kell (`%KÖZGÁZ%DSK/B%`).
- **Scoring run logika**: Window function-nel `opp_run_id`-t számol, a run az ellenfél utolsó pontja UTÁN kezdődik (lásd fentebb a Scoring run fejezetet).

### Szín- és dizájn rendszer
- **Közgáz arculat**: piros/fekete/fehér alapú szín paletta (a klub logójából)
- **CSS változók**: `--bg:#0a0b0e; --card:#151518; --accent:#C41E3A; --accent2:#00cec9; --accent4:#fdcb6e; --green:#00b894; --red:#e17055`
- **Szemantikus színek** (csapat dashboard):
  - Zöld (`--green`): pozitív értékek (győzelem, legtöbb dobott, saját run, pozitív különbség)
  - Piros (`--red`): negatív értékek (vereség, kapott pontok, kapott run, negatív különbség)
  - Teal (`--accent2`): semleges infó (dobott átlag, összes dobott, keretlétszám)
  - Kül./m: dinamikusan zöld vagy piros (érték alapján)
- **Chart színek**: Dobott vonal/oszlop = teal (#00cec9), Kapott = piros (#e17055)
- **Doughnut** (dobástípusok): teal / sárga / szürke (mind semleges)
- **Badge-ek**: W = zöld, L = piros, H (hazai) = steel blue (#8fa8c8), V (vendég) = sárga
- **Naptár**: lejátszott meccsek zöld/piros, jövőbeli meccsek szürke (semleges)

## Ismert limitációk

1. **7 képes PDF (Nyugat, Kandó SC hazai)** — Az egész oldal egyetlen raszterképként van exportálva, PyMuPDF nem tud szöveget kinyerni. OCR-rel feldolgozható lenne. Érintett: Kandó SC (7 meccs) + 7 ellenfél (1-1 meccs).
2. **2 TYPE3 hiányos grid** — F2KA-0095 és F2KA-0163 running score gridje nem tartalmazza az utolsó pontokat. A meccs-eredmény korrekt, csak a scoring_events részletesség érintett.
3. **Hosszabbítás (OT)** — A kód kezeli, de kevés OT meccs volt a tesztelésben.
4. **Más bajnokságok** — A rendszer elvileg bármely MKOSZ bajnokságra működik (NB1, U20, stb.), de csak NB2-re volt tesztelve. Más bajnokságok más PDF template-et használhatnak.
5. **README.md elavult** — Egyetlen meccsre vonatkozik, a teljes pipeline-t ez a CLAUDE.md dokumentálja.
6. **`shot_type` oszlop megbízhatatlan** — A `scoring_events.shot_type` a running score grid színezéséből jön, ami néha pontatlan (pl. continuation FT-k 3FG-nek jelölve). Mindig a `points` delta-t használd osztályozásra, NE a `shot_type`-ot.
7. **Alapszakasz adatok** — A játékos/csapat dashboardok jelenleg a 2025/26-os alapszakasz adatait tartalmazzák (SQLite-ból). A meccsnaptár viszont az MKOSZ weboldalról scrape-el, tehát automatikusan frissül ha rájátszás meccseket kiírnak.
8. **MKOSZ scraping** — A naptár az MKOSZ oldal HTML struktúrájától függ. Ha az MKOSZ megváltoztatja a táblázat formátumát, a regex-eket frissíteni kell a `scrape_schedule()` függvényben.
9. **Leftoverz** — A menüben szerepel de nincs hozzá tartalom/oldal. A csapat más néven/ligában játszhat.

## Lehetséges továbbfejlesztések

- Leftoverz csapat oldala (jelenleg placeholder a menüben)
- Összesített liga-szintű dashboard (összes csapat)
- Playoff/rájátszás játékos statisztikák integrálása a dashboardokba (SQLite oldalon)
- Dobáshatékonyság (FG%, 3FG%) hozzáadása a dashboardokhoz
- Percenkénti statisztikák (ha a playing time elérhető lenne)
- Meccs-összefoglaló oldal egy adott meccshez (mindkét csapat nézőpontjából)
- Naptárban meccsre kattintva részletes stat popup / link a játékos dashboardokhoz

## Aktuális állapot (2026-03-14)

Minden működik és szinkronban van:
- ✅ `scoresheet.sqlite` — 368 meccs feldolgozva (alapszakasz, 2025/26)
- ✅ Teljes site — főoldal + 18+18 játékos + 2 csapat + 2 naptár dashboard
- ✅ Meccsnaptár — MKOSZ weboldalról scrape-elve, lejátszott + jövőbeli meccsek
- ✅ Custom domain — www.kozgazkosar.hu (GitHub Pages, HTTPS)
- ✅ Közgáz arculat — piros/fekete szín, nav bar, hierarchikus vissza gombok
- ✅ Szemantikus színek — zöld=pozitív, piros=negatív, teal=semleges (csapat dashboard)
- ✅ Mezszámok — játékos index oldalakon sorszám helyett valódi mezszám
- ✅ Edzéslátogatás — Google Sheets-ből automatikusan fetch-elve (Közgáz B only)
- ✅ GitHub Actions — naponta frissíti az edzéslátogatás adatokat a weboldalon
- ✅ Minden commit pusholva a GitHub-ra
