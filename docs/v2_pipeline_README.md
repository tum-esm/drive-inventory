# DRIVE v2: how the emission chain works

This page shows the current logic of the `drive` package (branch `v2`) as flow charts. It covers the whole chain from the source data to the output products:

- **Hot emissions:** exhaust and non-exhaust.
- **Cold start excess emissions.**
- **Outputs:** line sources, summary tables and gridded emissions.

Details are in the topic pages linked below. Decisions (D…) and backlog items (R…) refer to the v2 spec.

## Overview

Ingest commands load each source into one DuckDB store. `drive run` reads only the store and writes the results.

```mermaid
flowchart LR
    subgraph sources[Sources]
        C1["LHM detector exports<br/>+ detector-link matching"]
        C2["BASt station files and raw archives<br/>+ station-link matching"]
        V1["VISUM link and zone exports<br/>2019 and 2025 models"]
        H1["HBEFA tables<br/>(local files or web API)"]
        K1["holidays package<br/>+ override file"]
        M1["DWD hourly temperatures"]
        G1["BKG VG250 boundaries"]
    end
    subgraph ingest["drive ingest &lt;source&gt; config.yaml"]
        IL[lhm]
        IB["bast (--download)"]
        IV[visum]
        IH["hbefa (--download)"]
        IK[calendar]
        IM[meteo]
        IG["boundaries (--download)"]
    end
    subgraph store["DuckDB store: append-only, versioned batches"]
        T1[(counts)]
        T2[(counter_links)]
        T3[(links / zones)]
        T4[(emission_factors)]
        T5[(calendar)]
        T6[(temperatures)]
        T7[(boundaries)]
    end
    R["drive run config.yaml"]
    O["data/inventory/v2/<br/>linesource_*.gpkg, grid_*.gpkg,<br/>summary_*.csv, profiles"]

    C1 --> IL --> T1 & T2
    C2 --> IB --> T1 & T2
    V1 --> IV --> T3
    H1 --> IH --> T4
    K1 --> IK --> T5
    M1 --> IM --> T6
    G1 --> IG --> T7
    T1 & T2 & T3 & T4 & T5 & T6 & T7 --> R
    R --> O
```

- **Versioning:** every ingest writes a new batch only if its input changed. A run reads the store as of `run.data_version` (a batch id or a time stamp; empty means the latest batch), so it can be reproduced later.
- **Counter link overrides:** corrections of the manual detector -> link matching are kept in git in `configs/counter_link_overrides.csv`, one row per detector with a reason (move to another link, or exclude; optionally per traffic model). They are applied when a run reads the matching (`pipeline.load_counter_links`, spec R26). Today: BASt 97742 moved to the eastbound carriageway 48217.
- **BASt sources:** the counts come from the annual station files for 2018–2020 and from the raw archives from 2021 on. `drive ingest bast --download` is meant for a monthly cron job. See [bast_counts_README.md](bast_counts_README.md).

## `drive run`: from counts to emissions

```mermaid
flowchart TD
    subgraph counts_qa["1. Counts QA: pipeline.load_link_counts, domain/counts_qa.py"]
        A1["Raw counts of the counts period<br/>(counts_qa.period_start to period_end)"]
        A2["Sum detectors per road link, date and vehicle class;<br/>drop link-days with a missing hour (BASt flags a, d, x)<br/>or a missing detector (D28); attach road type and day type"]
        A3["Drop days whose hours don't add up to the daily value (2.5 %)<br/>and days at or below the minimum daily value"]
        A4["Drop outliers: modified z-score above 3.5<br/>per link, vehicle class and day type group"]
        A4b["Drop implausible annual LCV shares per link and year:<br/>robust z of the log share above 3.5<br/>within scaling road type and year (D26)"]
        A5["valid: SQV of the reference-year normal-weekday mean<br/>against the model DTV above 0.6;<br/>otherwise the counter is dropped for every year"]
        A6["complete for year Y: SUM data on at least 80 % of the days<br/>of the reference year and of Y (D29);<br/>only valid and complete rows go into Activity"]
        A1 --> A2 --> A3 --> A4 --> A4b --> A5 --> A6
    end
    subgraph activity["2. Activity: domain/activity.py"]
        B1["Annual cycle per scaling road type and date:<br/>each link divided by its mean on normal weekdays<br/>of the reference year, then the median over links"]
        B2["Vehicle shares per scaling road type and date;<br/>BUS and MOT pooled over the city road types (D30)"]
        B3["Diurnal cycles per year, month, day type group and vehicle class"]
    end
    subgraph links["3. Links and factors"]
        L1["Links of the traffic model, clipped to the VG250 area of run.clip_ags<br/>(a split link gives one row per piece)"]
        L2["Share correction per link: model HGV share<br/>over the counted share on reference normal weekdays<br/>(LCV not corrected, D25)"]
        L3["Hot emission factor table per ambient pattern (D32):<br/>los_specific: per road type, speed, gradient and LOS<br/>aggregated: one mean factor per vehicle class"]
        L4["Hourly temperature (DWD, main and backup station)<br/>→ HBEFA ambient pattern of every hour"]
    end
    K["4. Hot emission kernel<br/>(next chart)"]
    CS["5. Cold starts<br/>(chart below)"]
    OUT["6. Outputs: line sources, summary, grids"]

    A6 --> B1 & B2 & B3
    B2 --> L2
    L1 --> L2
    L1 --> L3
    B1 & B2 & B3 & L2 & L3 & L4 --> K
    B1 & B2 & B3 & L4 --> CS
    K & CS --> OUT
```

Topic pages:

- [day_grouping_README.md](day_grouping_README.md): which days are normal weekdays (the scaling reference), and how days are grouped for the diurnal cycles, gap filling and outlier checks.
- [vehicle_classes_README.md](vehicle_classes_README.md): the vehicle classes of each source, the split of a link's volume into classes, the share corrections, the pooled BUS and MOT shares, the LCV share check and the HGV cap.
- [bast_counts_README.md](bast_counts_README.md): BASt sources, formats, flags, and how the counts QA uses the flags.
- [hot_emission_factors_README.md](hot_emission_factors_README.md): selection of the hot factors, including the hourly ambient temperature.

## The kernel, one day at a time

`domain/kernel.py:hot_emissions` loops over the days of the year. Within a day, all links and hours are computed at once with NumPy.

```mermaid
flowchart TD
    D0["Day d"] --> D1["Daily volume per link:<br/>dtv_SUM × annual cycle of the link's scaling road type"]
    D1 --> D2["Vehicle split: HGV = volume × share × hgv_corr (capped at the total, D27),<br/>LCV = volume × share (counted, D25),<br/>PC, MOT, BUS × factor k ≥ 0 that keeps the total"]
    D2 --> D3["Hourly volume: × diurnal cycle per vehicle class"]
    D3 --> D4["Car units per hour (HBS 2015 factors)"]
    D4 --> D5["Volume/capacity ratio = car units / hour_capacity"]
    D5 --> D6["LOS class 0-4 = number of thresholds of the road type<br/>strictly below the ratio<br/>(Freeflow, Heavy, Satur., St+Go, St+Go2)"]
    D6 --> D7["Add the hourly volumes to an annual total<br/>per link, LOS class, vehicle class and the hour's ambient pattern"]
    D6 --> D8["Add volume × link length to the hourly profile<br/>per hour, factor group and LOS class"]
    D7 --> E1["After the last day: annual volume × emission factor<br/>of the link, LOS class, vehicle class, component and pattern<br/>= g/km per link"]
    D8 --> E2["Hourly profile × factors of the hour's pattern<br/>= g per hour, road type, vehicle class and component"]
```

- **Speed:** emissions are linear in volume, and a link's factor depends only on its LOS class and the hour's ambient pattern. So the kernel only sums volumes per LOS class and pattern during the loop, and applies the factors once at the end. A year takes about 20 s, instead of v1's 46 min.
- **Ambient pattern:** only NOx and NO2 of PC and LCV depend on it. `run.hot_ambient: fixed` with `T+25°C,tØ,dØ` reproduces v1.
- **Errors and reports:** the kernel stops with an error before computing if a factor is missing, and on any day with missing or NaN activity. It reports the links on which the HGV cap acted.

## Cold starts

`pipeline.compute_cold_emissions`, `domain/cold_start.py`:

```mermaid
flowchart TD
    Z1["Daily starts per zone and class (PC, LCV)<br/>from the VISUM zones"] --> Z2["Distribute each zone's starts to the links of<br/>Access-residential, Local/Collector and Distributor/Secondary<br/>within 1.5 km, weighted by their dtv_SUM"]
    Z2 --> Z3["Clip to the boundary"]
    Z4["Hourly activity of the class on Distributor/Secondary:<br/>daily scaling × share / reference share × diurnal cycle (R40)"] --> Z5
    Z3 --> Z5["Starts per hour"]
    Z6["Hourly temperature → HBEFA start factor pattern<br/>(nearest 5 K bin)"] --> Z7
    Z5 --> Z7["× start factor (g/start) of the hour's pattern<br/>= g per hour, then distributed to the links"]
```

## Outputs

`drive run` writes, per run, line sources and a summary table:

- `linesource_<stem>.gpkg`: layers `hot` and `cold`, g/km per link piece.
- `summary_<stem>.csv`: t per kind, road type, vehicle class and component.

For each grid in `outputs.grids` (TNO 100 m and 1 km), it also writes `grid_<name>_<stem>.gpkg`, with layers `hot`, `cold` and `total` in kg per cell and component. Hourly profiles and time-profile factors are written as before. All products add up to the same totals. See [outputs_README.md](outputs_README.md).

## Settings per traffic model

The VISUM models represent the average normal-weekday traffic of their year, so each model is scaled relative to the normal weekdays of its own year. `scripts/run_series.py` sets this per run (D31). 2025 is computed with both models, so their estimates for the same year can be compared.

| Years | Traffic model | Reference year | Counts period |
|---|---|---|---|
| 2018–2025 | `visum2019` | 2019 | 2018–2025 |
| 2025 on | `visum2025` | 2025 | 2019–2025 |

Known caveat: in 2018 most city detectors only report from December. The 2018 scaling of the city road types therefore rests on 1–4 counters (R47).

## Checks

| What | How |
|---|---|
| Kernel, scaling, vehicle split, pooling, counts QA, gridding, output units, store versions | `uv run pytest`, known-answer tests on invented data (`tests/`), also in CI |
| Code | `uv run ruff check`, `uv run pyright`, also in CI |
| Results against v1 | `scripts/compare_v1_*.py` on the real data, against the baselines in `data/inventory/baselines/`; local only. They stay exact on v1's own inputs and report the differences of the v2 chain |
| Counted vs modelled shares per counted link | `scripts/check_link_shares.py [config] [scaling road type]` |
| Whole series | `scripts/run_series.py`, compared with the latest baseline (currently `v2.10-counteroverrides`) |
| Output contracts | `drive/schemas.py` (line sources, summary, grids, profiles: keys, CRS EPSG:25832, finite values, hot ≥ 0, naive local hours), checked whenever `drive run` writes |
