# Vehicle classes and share corrections

DRIVE splits the traffic on every link into five vehicle classes: PC, LCV, HGV, BUS and MOT. This page describes how the classes of each data source map to them, how the split is computed, and which corrections are applied and why.

## Classes

| DRIVE | Meaning | HBEFA vehicle category |
|---|---|---|
| PC | passenger cars, including cars with a trailer | `pass. car` |
| LCV | light commercial vehicles up to 3.5 t | `LCV` |
| HGV | heavy goods vehicles over 3.5 t, with and without trailer, articulated trucks | `HGV` |
| BUS | buses and coaches | `coach` |
| MOT | motorcycles | `motorcycle` |
| SUM | all motor vehicles | – |

The HBEFA mapping is in `drive/io/hbefa.py` (`VEHICLE_CLASSES`).

## Assignment per source

### BASt permanent counting stations

BASt stations classify vehicles into the 8+1 classes of TLS 2012 (`drive/io/bast.py`, `CLASSES`):

| DRIVE | BASt columns |
|---|---|
| SUM | `KFZ` |
| PC | `Pkw` + `PmA` (car with trailer) |
| LCV | `Lfw` (Lieferwagen) |
| HGV | `LoA` (truck without trailer) + `Lzg` (truck with trailer, including articulated trucks) |
| BUS | `Bus` |
| MOT | `Mot` |

`Lzg` already contains the articulated trucks (`Sat`), so `Sat` isn't added again. `PLZ` (cars, vans and motorcycles together, from stations with 5+1 classification) and `Son` (not classifiable, about 0.2 % of `KFZ`) aren't used. Station-years without a class split give SUM only. See [bast_counts_README.md](bast_counts_README.md) for formats and flags.

### LHM detectors (city of Munich)

The city's detectors give volumes per class (`drive/io/lhm.py`, `VOLUME_CLASSES`):

| DRIVE | LHM `ART` |
|---|---|
| SUM | `QKFZ` |
| PC | `QPKW` + `QPKWA` (car with trailer) |
| LCV | `QLFW` |
| HGV | `QLKW` + `QLKWA` + `QSATTEL_KFZ` |
| BUS | `QBUS` |
| MOT | `QKRAD` |

### VISUM traffic models

The models give the average weekday traffic per directed link (`drive/io/visum.py`):

| DRIVE | VISUM field |
|---|---|
| `dtv_SUM` | `SUMME_KFZ` |
| `dtv_PC` | `BEL_PKW` |
| `dtv_LCV` | `BEL_LKW_K` (small trucks) |
| `dtv_HGV` | `BEL_LKW_M` + `BEL_LKW_G` (medium and large trucks) |

The models represent total traffic. `dtv_SUM` equals PC + LCV + HGV, and PC implicitly contains motorcycles and buses (spec D23).

The class fields are rounded to whole vehicles, while `SUMME_KFZ` isn't. So PC + LCV + HGV differs from `dtv_SUM` by up to 2 vehicles per day (mean 0.5). On links with only a few vehicles a day this matters: in visum2025, 156 links have more HGV than vehicles in total (for example 2 HGV in a total of 1.49). See [Negative volumes](#negative-volumes).

## How a link's volume is split

For every day the kernel (`drive/domain/kernel.py`) does the following:

1. It scales the link's model volume `dtv_SUM` with the daily factor of its scaling road type.
2. It splits the scaled volume with the counted vehicle shares of that scaling road type and day. These shares are the median volume per class over the complete and valid counted links, divided by the sum over the classes (`Activity.vehicle_shares`).
3. It applies the share corrections per link:

```text
h = min(hgv_corr · share_HGV, 1)          corrected HGV share, at most the total
l = min(lcv_corr · share_LCV, 1 − h)      corrected LCV share, at most what HGV leaves
HGV = volume × h
LCV = volume × l
PC, BUS, MOT = volume × share × k,   k = (1 − h − l) / (1 − share_HGV − share_LCV)
```

The factor `k` keeps the total unchanged: whatever HGV and LCV gain, PC, BUS and MOT lose. The caps keep `k` at 0 or above, so no class gets a negative volume, see [Negative volumes](#negative-volumes).

## Share corrections

All links of a scaling road type share one temporal profile and one vehicle share per day. The correction factors bring back spatial differences between the links:

```text
corr = model share of the link / mean counted share of its scaling road type on the reference days
```

Here the reference days are the normal weekdays of the reference year. On a reference day a corrected link therefore carries exactly its model share. On other days the counted share's change relative to the reference days is applied on top.

### HGV: corrected (`hgv_corr`)

Checked with `scripts/check_link_shares.py` on the motorway counting stations (spec R43, normal weekdays):

| | visum2019 (2019) | visum2025 (2025) |
|---|---|---|
| HGV share, counted / model, mean over links | 13.3 % / 13.4 % | 11.7 % / 12.9 % |
| correlation counted ↔ model per link | 0.88 | 0.93 |
| model / counted, volume-weighted | 0.99 | 1.11 |

The model reproduces the spatial HGV pattern well. For example, it separates the freight corridors (A9, A92, A99 east, 16–22 % HGV) from the low-HGV motorways in the west (2–6 %). So the correction stays. On the low-HGV motorways the 2025 model is 50–95 % too high. This is a known limitation.

### LCV: not corrected (`lcv_corr = 1`)

Since spec D25 (2026-11-16) every link uses the counted LCV share of its scaling road type. v1 corrected LCV like HGV.

The reasons, from `scripts/check_link_shares.py` (spec R43, R44):

| Road type, visum2025 | counted LCV share | model LCV share | model / counted | correlation per link |
|---|---|---|---|---|
| Motorway-Nat (BASt) | 11.7 % | 17.0 % | 1.47 | −0.05 |
| TrunkRoad/Primary-City (LHM) | 11.0 % | 19.7 % | 1.83 | 0.01 |
| Distributor/Secondary (LHM) | 10.2 % | 14.6 % | 1.43 | 0.37 |

- **Level:** the model's LCV share is 1.4 to 1.9 times the counted share on every road type. With visum2019 it is 1.54 times on the motorways.
- **Pattern:** the model's LCV shares don't follow the counted spatial pattern, so a correction would add the model's pattern rather than a real one.
- **Two counting networks agree:** the BASt stations (federal roads) and the LHM detectors (city roads) are independent networks, and both count 10–12 % LCV.
- **The BASt class is consistent:** the two directions of a station agree (median deviation 3 %, HGV 5 %). Year to year a station's share changes by ±2–5 % (interquartile range). The weekly pattern fits commercial traffic: on Sundays LCV is 49 % of its normal-weekday volume, PC 93 % and HGV 9 %. There's no summer peak on weekdays, which would point to camper vans.

**Limits of the counted LCV share.** It is a share of vehicles classified by length and shape, while HBEFA's LCV class is defined by registration and mass:

- TLS 2012 requires a detection rate for `Lfw` of 90/85/80 % (accuracy groups A1/A2/A3), against 97/95/90 % for Pkw. BASt's own census merges Pkw and `Lfw` (R SVZ 2030, Table 1 and Table 6).
- Camper vans and minibuses with up to 9 seats are defined as Pkw, but probably counted as `Lfw` by their shape. Small vans may be counted as Pkw.
- A bias of ±10–20 % in the counted LCV share is therefore plausible. The factor of 1.4–1.9 between model and counts isn't explained by it.

Some detectors count LCV far off. The counts QA removes those link-years, see [Implausible class shares](#implausible-class-shares).

**Open question:** the VISUM model's LCV definition (`BEL_LKW_K`). For example, commercial passenger cars counted as LCV would explain the higher level. The question is for the model provider.

**Effect (series 2018–2025 against `v2.2-rawcounts`):** hot LCV emissions fall by 34–38 %, and PC, BUS and MOT rise by 6–8 % through the factor `k`. Hot CO2(rep) as a whole falls by 1.2–1.8 % per year, because LCV emit more per kilometre than PC. HGV changes by −0.4 to −0.7 % (0 % in 2018). The reason is that BUS volume rises and counts 1.75 car units in the volume/capacity ratio, so more links reach a higher level of service. Links with negative volumes (`k < 0`, before the cap of D27): 2025 32 instead of 16, 2018 87 instead of 107. A low `lcv_corr` used to offset a high `hgv_corr` on some links. Cold starts don't change. Baseline: `data/inventory/baselines/v2.3-countedlcv`.

| Hot, % against `v2.2-rawcounts` | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| CO2(rep), all classes | −1.16 | −1.43 | −1.65 | −1.77 | −1.69 | −1.62 | −1.66 | −1.27 |
| LCV CO2(rep) | −37.5 | −37.8 | −37.9 | −37.9 | −37.9 | −37.9 | −38.0 | −34.5 |
| PC CO2(rep) | +7.2 | +6.5 | +7.4 | +7.7 | +7.5 | +7.5 | +7.1 | +6.4 |
| NOx LCV | −37.6 | −38.0 | −38.0 | −38.0 | −38.0 | −38.0 | −38.1 | −34.3 |

## Implausible class shares

Detectors classify by length and shape. A faulty or misconfigured detector can count one class far off while its total (SUM) stays right. The counts QA (`drive/domain/counts_qa.py`, `_drop_share_outliers`, spec D26) therefore checks every link's annual class share against the other links of the same scaling road type in the same year:

1. Annual share per link, year and class: the class volume divided by SUM, summed over the days on which both are counted. Link-years with fewer than `share_min_days` (30) such days aren't checked.
2. Robust z-score of the log share within scaling road type, year and class: `z = 0.6745 · (log share − median) / MAD`. This is the same method as the daily outlier step. On the log scale, half and double the median are equally far off.
3. If `|z| > share_z_threshold` (3.5), the class's counts on that link are removed for that year. SUM and the other classes stay, so the link still counts for the totals and the other shares. Groups with fewer than `share_min_links` (5) link-years aren't checked.

The rule uses no station lists or source-specific ids, so it works for any city and counting network. The settings are under `counts_qa` in the config. `share_check_classes: []` switches the check off.

Only LCV is checked (`share_check_classes: [LCV]`). For HGV the spread between links is real: the median absolute deviation of the log share is 0.4–0.5, against 0.08–0.12 for LCV. The HGV links the rule would flag are plausible, for example industrial roads with 24 % HGV.

In the Munich data the check removes 41 link-years on 11–12 links (`drive run` prints the count):

| Detector | Road type | Years | LCV share | × median | Likely cause |
|---|---|---|---|---|---|
| BASt 99851, 99852 | Motorway-Nat | 2021–2025 | 26–27 % | 2.6 | faulty classification (99851 is back to 12 % in 2025) |
| BASt 91401 | Motorway-Nat | 2021, 2025 | 0.6 %, 5.8 % | 0.05–0.5 | faulty classification |
| BASt 92152 | Motorway-Nat | 2019–2025 | 4.7 % | 0.46 | the other direction (92151) counts 13 % |
| BASt 99872 | Motorway-Nat | 2021–2022 | 4.4–4.9 % | 0.45 | low against the station's later years |
| LHM 4035011 | Distributor/Secondary | 2019–2025 | 0.1–4.7 % | 0.01–0.5 | 2019–2020 practically no LCV and HGV: the detector didn't classify |
| LHM 4035, 4037, 4041 | TrunkRoad/Primary-City, Distributor | 2019–2020 | 4.5–5.8 % | 0.5–0.7 | low in these years, normal afterwards |
| LHM 4171 | Distributor/Secondary | 2019–2025 | 5.1 % | 0.57 | constant over the years; may be a real local feature |
| LHM 4157 | Distributor/Secondary | 2023–2025 | 14 % | 1.6 | may be a real local feature |

Constant deviations, as on 4171 and 4157, may be real. The rule can't tell those from a misconfigured detector. Removing them costs little, because the share per road type is a median over many links.

Not caught: step changes in the share that stay inside the normal range. Several BASt stations jump by +27–51 % from 2023 to 2024 (9063, 9066, 9083, 9115, 9772, 9986), probably after device or parameter changes, and it's open which level is right.

**Effect (series 2018–2025 against `v2.3-countedlcv`):**

| | Change |
|---|---|
| Hot CO2(rep), all classes | within ±0.02 % |
| Hot LCV | −0.5 to +1.3 % |
| Cold LCV, 2024 | −2.3 % |
| Cold LCV, other years | within ±0.2 % |

The effect is small because the vehicle shares are already a median over the links, so a single faulty link moves them little. The check matters more where few links are counted, and it keeps faulty detectors out of the LCV diurnal cycles. Baseline: `data/inventory/baselines/v2.4-sharecheck`.

## Negative volumes

The split keeps each link's total fixed. HGV and LCV are set first; PC, BUS and MOT share what is left through the factor `k`. Without a cap (v1), `k` turns negative when the corrected HGV and LCV volumes together exceed the link's total:

```text
hgv_corr · share_HGV(day) + share_LCV(day) > 1
```

PC, BUS and MOT then got negative volumes, so that the total still held. Two things push a link there.

1. **The model gives the link (almost) only HGV.** `hgv_corr` is the link's model HGV share over the road type's reference share. On Distributor/Secondary the reference share is 3.65 %, so a link with 97 % HGV in the model gets `hgv_corr` = 26.6. On a normal weekday of the reference year it carries 97 % HGV, as the model says.
2. **The counted HGV share rises on other days.** It moves with the day:

   | Distributor/Secondary 2025 | Mean HGV share | Maximum |
   |---|---|---|
   | Normal weekdays (reference) | 3.65 % | 8.0 % |
   | Vacation weekdays | 5.1 % | 8.5 % |

   During school vacations car traffic drops and trucks keep driving. The link then gets 26.6 × 5.1 % = 136 % HGV, more than its total, and PC, BUS and MOT went negative to compensate.

The rounding of the VISUM class fields makes it worse. A link with a total of 1.49 vehicles and 2 HGV has a model HGV share of 134 %, so it's above 100 % already on the reference days.

In visum2025, 83 link pieces would get `k < 0` on at least one day:

| | Median | Range |
|---|---|---|
| Model HGV share | 97 % | 41–134 % |
| Total (`dtv_SUM`) | 10 vehicles per day | up to 561 |
| Days with `k < 0` | 124 | 1–257 |

These are mostly short access links to truck terminals, depots and industrial areas, or links with almost no traffic.

**Cap (spec D27, since 2026-11-16).** The kernel caps the corrected HGV share at 1 and the corrected LCV share at what HGV leaves (`kernel.daily_volumes`). On such a day the link carries only HGV (and LCV, if room is left), and PC, BUS and MOT are 0. The total stays unchanged and no volume is negative. `drive run` reports how many links the cap acted on (`links with the HGV cap`). `scripts/compare_v1_hot.py` checks the kernel against v1 with `KernelParams(cap_shares=False)`, because v1 let `k` go negative.

**Effect (series 2018–2025 against `v2.4-sharecheck`):** the cap acts on 47–125 links per year (125 in 2018, 83 in 2025). Hot HGV changes by −0.07 % in 2018 and by less than 0.005 % in the other years. Every other class and cold starts change by less than 0.01 %. Baseline: `data/inventory/baselines/v2.5-hgvcap`.

## Cold starts

Cold starts are computed for PC and LCV from the model's daily starts per zone and class (`PC_starts`, `LCV_starts`). They are scaled with the class's own counted activity relative to its share on the reference days (`cold_start.start_scaling: vehicle_specific`, spec R40), so `lcv_corr` doesn't enter. The zone starts come from the same model as the LCV volumes. Whether they share its higher LCV level is open.

## Checks

- `scripts/check_link_shares.py [config] [scaling_road_type]`: counted vs model volumes and shares per counted link
- `tests/test_counts_qa.py`: the share check removes only the faulty class and year of a link
- `tests/test_kernel.py`: the class split by hand, with and without the HGV cap
- `scripts/compare_v1_hot.py`: checks the kernel exactly against v1. It passes `classes=('HGV', 'LCV')` to `share_corrections` to reproduce v1's corrections.

## Sources

- BASt, [Richtlinien für die Straßenverkehrszählung 2030 auf Bundesfernstraßen](https://www.bast.de/DE/Publikationen/Statistik/Verkehrsdaten/2030/Richtlinien-2030.pdf?__blob=publicationFile&v=2), Table 1 (vehicle classes), Table 6 (detection rates after TLS 2012, Table IV-14)
- BASt, [Datensatzbeschreibung DZ (format 2004)](https://www.bast.de/DE/Publikationen/Daten/Verkehrstechnik/Downloads/DZ-Beschreibung.pdf?__blob=publicationFile)
