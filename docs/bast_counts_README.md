# BASt counting data: download and processing

DRIVE uses hourly counts from the automatic permanent counting stations (*Dauerzählstellen*) of the Federal Highway Research Institute (BASt) on motorways and federal roads around Munich. This page records where the data comes from, which formats it arrives in, and how DRIVE reads it. If BASt changes a URL, a file format or a code, compare the new state against what is written here.

Status (13 November 2026): the reader for the hourly station table is done, `drive/io/bast.py` (step 2a). The reader for the raw files (2b) and the download command `drive ingest bast --download` for a monthly cron job (2c) are planned. Until 2c, the store holds v1's preprocessed BASt counts (batch 2).

## Sources

All files are public. Hourly values are counts per hour, with hours numbered 01:00 to 24:00 (the hour *ending* at that time).

| Product | URL | Coverage (Nov 2026) | Status of the data |
|---|---|---|---|
| Annual station files | `https://www.bast.de/videos/<year>/zst<station>.zip`, one zip per station and year with `zst<station>_<year>.csv` | up to 2024; 2025 answers 404 | quality-checked, final |
| Raw data (*Rohdaten*), per year | `DZ_<year>_Rohdaten.zip`, links on the page below | 2021–2025 (2025: 925 MB) | not checked, provisional |
| Raw data, per month | `DZ_<year>_<month>_Rohdaten.zip`, links on the page below | 2026-01 to 2026-08, about 2–3 months behind (2026-08: 80 MB) | not checked, provisional |
| Format description | `https://www.bast.de/DE/Publikationen/Daten/Verkehrstechnik/Downloads/DZ-Beschreibung.pdf` | "BASt-Bestandsbandformat für Verkehrsmengendaten, Version 2004" | |

The raw-data links are listed on `https://www.bast.de/DE/Publikationen/Daten/Verkehrstechnik/DZ.html` and point to `files.bast.de` (a Nextcloud share, `.../index.php/s/<token>/download/<file>`). The tokens change with every file, so the links must be read from the page; they can't be built. The share answers HEAD requests with 401; a GET (or a range request `-r 0-0` to read the size) works.

BASt's own note on the raw data: it is neither checked for plausibility nor processed, and may contain gaps, incomplete cross-sections, wrong directions, time shifts, wrong vehicle classification, format errors and wrong values.

## Formats

### Annual station table

One row per station and hour, semicolon-separated, values right-aligned with leading spaces. Both directions are in the same row.

```text
TKNR;Zst;Land;Strklas;Strnum;Datum;Wotag;Fahrtzw;Stunde;KFZ_R1;K_KFZ_R1;KFZ_R2;K_KFZ_R2;Lkw_R1;K_Lkw_R1;...;Son_R2;K_Son_R2
7834;9140;09;A;   8;240101; 1;s;01;  174;s;  158;-;    0;a;    0;a;...
```

| Column | Meaning |
|---|---|
| `TKNR` | sheet number of the 1:25,000 topographic map |
| `Zst` | station number (four digits) |
| `Land`, `Strklas`, `Strnum` | state code (`09` Bavaria), road class (`A`, `B`), road number |
| `Datum` | date `yymmdd` |
| `Wotag`, `Fahrtzw` | weekday (1 = Monday), day category |
| `Stunde` | hour `01`–`24` |
| `<class>_R1`, `<class>_R2` | count in direction 1 or 2 |
| `K_<class>_R1`, `K_<class>_R2` | flag of that count, see below |

Classes in the table: `KFZ` (all vehicles), `Lkw` (heavy vehicles), `PLZ`, `Pkw`, `Lfw`, `Mot`, `PmA`, `Bus`, `LoA`, `Lzg`, `Sat`, `Son`. Checked on the Munich files for 2018–2026: `Mot + Pkw + Lfw + PmA + Bus + LoA + Lzg + Son = KFZ` exactly (median ratio 1.000), and adding `Sat` overshoots by 2–6 %. So `Lzg` already contains the articulated trucks (`Lzg = LmA + Sat`). `Lkw = LoA + Lzg + Bus`.

### Raw data (fixed width)

One file per station and month, named `<state><station>.<yy><month code>`, e.g. `BY9140.268` for August 2026. Month codes are `1`–`9`, then `a`, `b`, `c` for October to December. A version suffix (`BY9140_1.268`) marks a change of the data structure during the year. The monthly zip also holds `_DZ_<year>_<month>_Metadaten.csv` with name, road, directions and UTM32 coordinates per station (`;`-separated, Latin-1).

Three header lines, then one line per hour:

```text
H78349140 09 A 8     AK München-West (O)      V2.0;
R02 02 München             O Augsburg            W;
S02 09 KFZ SV  Mot Pkw Lfw PmA Bus LoA LmA Sat Son;
260801 01:00  196-    4-   28-    0-   57-    0k  194-   12-    0-  185-    4-    0- ...
```

| Line | Content |
|---|---|
| `H` | sheet number (2–5), station (6–9), state (11–12), road class (14), road number (16–20), name (22–46), format version (47–50) |
| `R` | lanes in direction I (2–3) and II (5–6), destination and compass direction of each direction |
| `S` | number of vehicle groups (2–3) and classes (5–6), then their names in the order of the values |
| hour | date `yymmdd` (1–6), status (7: `i` = inserted record, e.g. at the clock change), hour `hh:mm` (8–12), then fields of 6 characters: a space, the count right-aligned in 4 digits, and the flag |

Order of the values in an hour line: first the groups (e.g. KFZ, SV) for every lane, then the classes for every lane. Lanes run across the road from the counting device: direction I from the outer lane (FS1) to the overtaking lane, then direction II from its overtaking lane to its outer lane. Summing per direction makes the lane order irrelevant.

The `S` line tells the classification of the station:

| Classification | Classes in the file |
|---|---|
| 8+1 | KFZ, SV; Mot, Pkw, Lfw, PmA, Bus, LoA, LmA, Sat, Son |
| 5+1 | KFZ, SV; PLZ (= Mot + Pkw + Lfw), PmA, Bus, LoA, Lzg (= LmA + Sat), Son |
| 2 | KFZ, Lkw |
| 1 | KFZ |

### Flags

Every count has a one-character flag.

| Flag | Meaning (2004 description) |
|---|---|
| `-` | correct, regular value |
| `u` | correct but irregular value (e.g. a large event) |
| `a` | missing value (failure, even for a few minutes) |
| `d` | faulty value |
| `s` | estimate replacing a missing value |
| `k` | estimate correcting a faulty value |
| `z` | clock change (spring and autumn) |
| `x` | not in the 2004 description. Always comes with the value −1 and marks a class the station doesn't count |

KFZ flags in the Munich files, both directions, 2018: `-` 365,379, `s` 72,396, `u` 125, `z` 100. 2019 to January 2026: `-` 3,447,423, `s` 585,749, `a` 111,002, `k` 37,034, `u` 720, `z` 684.

## How v1 did it

1. `data/restricted_input/counting_data/bast/download_bast_data.ipynb` and `download_bast_data_v2.ipynb`:
   - `Process` downloaded the annual station zips of the stations in `bast_locations_selected.gpkg` and concatenated the CSVs.
   - `Process_raw` read the raw-data links from the BASt page and unzipped them into `temp_raw/`. `delete_unused_locations` removed the files of other stations, and `extract_append_raw_data` turned the fixed-width files into rows of the annual table: it added the lanes per direction, wrote `Lzg = LmA + Sat` and `PLZ = Mot + Pkw + Lfw`, copied the `Mot` flag to `PLZ`, set `Fahrtzw = 'n'` and filled missing values with 0. It expected one zip per month inside the yearly zip; the current monthly zips contain the station files directly.
2. The results are the merged tables used today:
   - `BAST_CountingStations_daily_2018.csv`: 25 stations, 2018, from the annual files.
   - `BAST_TrafficCounts_raw.csv`: 42 stations, 2019-01-01 to 2026-01-31. 2019–2022 come from the annual files. 2023 to January 2026 come from the raw data (every row has `Fahrtzw = 'n'`), although annual files for 2023 and 2024 exist now.
3. `notebooks/data_preprocessing/11_preprocess_bast_counting_data.ipynb` turned the table into v1's long format:
   - It dropped all flag columns (`K_*`).
   - One detector per direction: `detector_id = Zst + '1'` or `'2'`.
   - It mapped the classes, summed the hours to the daily value, set `detector_type = '8+1'` for every row, and joined `road_link_id` from `bast_locations_selected.gpkg`.
   - The result is `BAST_TrafficCounts_preprocessed*.parquet`, read by `drive ingest counts` (batch 2).

## How v2 reads it

`drive/io/bast.py`:

- `read_station_table(path)` reads an annual station file (`.csv` or the `.zip`) or one of v1's merged tables (comma-separated with an index column).
- `read_locations(path, model_link_ids)` reads the matching.

| Step | Rule |
|---|---|
| Detector | `Zst` + `1` or `2` (direction), as in v1 |
| Classes | SUM = `KFZ`; PC = `Pkw` + `PmA`; LCV = `Lfw`; HGV = `LoA` + `Lzg`; BUS = `Bus`; MOT = `Mot` (v1). `PLZ`, `Sat` and `Son` are not used |
| Hours | `Stunde` 01–24 → `h00`–`h23` |
| Daily value | sum of the hours (v1) |
| Negative values | −1 (flag `x`) read as missing; v1's preprocessed file had −1 |
| Hours without a row | missing, flag `a`; v1 filled 0 (126 station-hours, all on 23-hour days) |
| Flags | stored per hour in `counts.flags`, 24 characters. A class built from several columns gets the worst flag of its parts, in the order `- z u k s d a x` |
| Checks | missing columns, a station-hour appearing twice, or an unknown flag raise an error |

What v1 ignored, recorded as R41 in the backlog (how the counts QA should use the flags is still open):

- In many station-years the station counts no vehicle classes. Every class is then 0 with flag `a`, and v1 read those zeros as counts.
- Stations 9064, 9219, 9220 and 9242 counted 5+1 classes in 2018 and/or 2019. v1's PC is then only `PmA` (cars with trailers) and LCV is 0.

Classification per station and year, read from the merged tables (8+1: `Pkw` counted; 5+1: only `PLZ` counted; none: all classes `a`; empty: no data):

```text
Zst   18   19   20   21   22   23   24   25   26
9003  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9006  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9043       8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9063  8+1       8+1  8+1  none 8+1  8+1  8+1  8+1
9064  5+1  ?    8+1  8+1  8+1  8+1  8+1  8+1  8+1
9066  8+1  none none none none 8+1  8+1  8+1  8+1
9082                 8+1  8+1  8+1  8+1  8+1  8+1
9083                 8+1  8+1  8+1  8+1  8+1  8+1
9102                           none none none none
9106  none none 8+1  8+1  8+1  8+1  8+1  8+1  8+1
9115            none none      8+1  8+1  8+1  8+1
9140  none none none none none 8+1  8+1  8+1  8+1
9141  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9151                      8+1  8+1  8+1  8+1  8+1
9155  8+1  8+1  8+1       8+1  8+1  8+1  8+1  8+1
9207  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9211                           none none none none
9212  8+1  8+1                 none none 8+1  8+1
9213  8+1       8+1  8+1       8+1  8+1  8+1  8+1
9215  8+1  8+1  8+1            8+1  8+1  8+1  8+1
9217  8+1  8+1  none none none 8+1  8+1  8+1  8+1
9218                           8+1  8+1  8+1  8+1
9219  5+1  5+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9220  5+1  5+1       none 8+1  8+1  8+1  8+1  8+1
9221  none none none      8+1  8+1  8+1  8+1  8+1
9222  8+1            8+1  8+1  8+1  8+1  8+1  8+1
9228                 none none 8+1  8+1  8+1  8+1
9229                           8+1  8+1  8+1  8+1
9242  5+1  ?    8+1  8+1  8+1  8+1  8+1  8+1  8+1
9244  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9320                 8+1  8+1  8+1  8+1  8+1  8+1
9772  8+1  8+1  8+1       8+1  8+1  8+1  8+1  8+1
9773                           8+1  8+1  8+1  8+1
9774  none none none none none 8+1  8+1  8+1  8+1
9775  none none      none none 8+1  8+1  8+1  8+1
9810       none 8+1  8+1  8+1  8+1  8+1  8+1  8+1
9820       8+1  8+1  8+1  8+1  8+1  8+1  8+1  8+1
9830            8+1  8+1  8+1  8+1  8+1  8+1  8+1
9985  none none                8+1  8+1  8+1  8+1
9986                           8+1  8+1  8+1  8+1
9987  none none      none none 8+1  8+1  8+1  8+1
9988                 8+1  8+1  8+1  8+1  8+1  8+1
```

## Checking against this state

`uv run python scripts/compare_v1_bast.py` reads both merged tables with `read_station_table` and compares them with v1's preprocessed counts (store batch 2). Expected output (13 November 2026):

```text
v1 preprocessed (batch 2): 1155216 rows, 84 detectors, 2018-01-01 to 2026-01-31
BAST_CountingStations_daily_2018.csv: 109500 rows, 25 stations, 2018-01-01 to 2018-12-31, 0 station-hours without a row
BAST_TrafficCounts_raw.csv: 1045716 rows, 42 stations, 2019-01-01 to 2026-01-31, 126 station-hours without a row
rows only in v1 0, only in v2 0
hourly values: 27723672 equal, 1512 missing here ([0.] in v1), 0 other differences
daily values: max |diff| 0.0; differ in 0 rows
```

The 1,512 hourly values are the 126 station-hours without a row, times 2 directions and 6 classes.

After a change, check:

| Change | What to check |
|---|---|
| New annual year published | `https://www.bast.de/videos/<year>/zst9140.zip` answers 200. Its header must equal the one above, or `read_station_table` raises on missing columns |
| New flag | `read_station_table` raises on unknown flags. Add it to `FLAG_ORDER` in `drive/io/bast.py` and to the `flags` check in `drive/schemas.py` |
| Raw-data page or links | `DZ.html` still lists `files.bast.de` links named `DZ_<year>[_<month>]_Rohdaten.zip` |
| Raw-data layout | file names `<state><station>.<yy><month code>` and the `H`/`R`/`S` header lines as above; the format version in the `H` line (`V2.0`) |
| Class definitions | the class sums: without `Sat` they must equal KFZ, with `Sat` they must not |
| Station set | stations in `bast_locations_selected.gpkg` (42 stations, 84 detectors) |
