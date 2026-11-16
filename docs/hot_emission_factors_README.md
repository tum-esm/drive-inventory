# Hot emission factors

DRIVE takes hot (warm-engine) emission factors from HBEFA. Every link has a traffic situation per hour. The hot part of `drive run` multiplies the hourly volume per vehicle class with the factor of that traffic situation, gradient, vehicle class and component. This page describes how the factors are selected. The share corrections and class split are in [vehicle_classes_README.md](vehicle_classes_README.md).

## Factor tables

`drive ingest hbefa` stores one table per year, category and aggregation (`{year}_hot_single_ts_v{version}.parquet`, HBEFA version 501007). The tables hold eight ambient patterns, `T-10°C,tØ,dØ` to `T+25°C,tØ,dØ` in 5 K steps. `tØ` and `dØ` are the average trip length and parking time.

## Ambient temperature (spec R33, D32)

In HBEFA 5.1 the ambient temperature changes only one thing in the hot factors: NOx and NO2 of passenger cars and light commercial vehicles (the diesel NOx temperature correction). Every other component and vehicle class has the same factor in all eight patterns.

| Median ratio to the 25 °C factor, 2025 tables | −10 °C | 0 °C | +10 °C | +20 °C |
|---|---|---|---|---|
| PC NOx | 1.53 | 1.52 | 1.16 | 1.00 |
| PC NO2 | 1.59 | 1.58 | 1.18 | 1.00 |
| LCV NOx | 1.52 | 1.51 | 1.22 | 1.00 |
| LCV NO2 | 1.49 | 1.48 | 1.21 | 1.00 |

v1 always used the `T+25°C` factors, so hot NOx was too low in every month below 25 °C.

**Since D32:**

- **Pattern per hour:** `drive run` selects the pattern of every hour from the hourly air temperature (config `run.hot_ambient: hourly_temperature`).
  - The temperature is the same as for the cold starts (`run.temperature`): the DWD station 03379 München-Stadt, with gaps filled from 01262 München-Flughafen, converted to local time.
  - The pattern is the nearest 5 K bin, ties to the lower bin, as for the cold starts (`cold_start.start_patterns`). Hours below −10 °C or above 25 °C get the outermost pattern.
- **Kernel:** it sums the volume per link, level of service, vehicle class and pattern, and applies each pattern's factors. The hourly profile uses the factors of each hour's pattern.
- **v1 mode:** `run.hot_ambient: fixed` with `hot_ambient_pattern: T+25°C,tØ,dØ` reproduces v1. `scripts/compare_v1_hot.py` runs this way.

`drive run` prints the hours per pattern. Hours per pattern in 2025:

| −10 °C | −5 °C | 0 °C | 5 °C | 10 °C | 15 °C | 20 °C | 25 °C |
|---|---|---|---|---|---|---|---|
| 2 | 256 | 1451 | 1536 | 1856 | 1883 | 1051 | 725 |

**Effect (series against `v2.8-pooledbusmot`):**

| Hot, all classes | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| NOx | +14.0 % | +15.8 % | +14.6 % | +15.8 % | +13.6 % | +13.1 % | +12.6 % | +13.0 % |
| NO2 | +19.9 % | +20.5 % | +18.6 % | +19.5 % | +16.5 % | +15.7 % | +14.3 % | +14.0 % |

- **By class:** PC NOx rises by 15–23 % and LCV NOx by 20–26 %.
- **Over the years:** the effect becomes smaller, because newer cars depend less on temperature in HBEFA.
- **Everything else is unchanged:** CO2, PM, CO, CH4, HGV, BUS and MOT.

Baseline: `data/inventory/baselines/v2.9-hottemperature`.

## Other settings

- `run.hot_mode: los_specific` uses the traffic situation of each link and hour (level of service from the volume/capacity ratio). `aggregated` uses one mean factor per vehicle class and component; HBEFA's aggregate tables exist for 2024 and 2025 only.
- Gradients: uphill links use their own gradient (`+2%`, `+4%`, `+6%`, spec R34).
