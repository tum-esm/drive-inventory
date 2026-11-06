# Day grouping

DRIVE scales traffic differently depending on the kind of day. This page describes how each date gets a day type, where the day types are used, and how the calendar module works.

## Day types

Every date has exactly one day type. The first matching rule wins, so a public holiday during a school vacation is a holiday.

| Code | Day type | Rule |
|---|---|---|
| 4 | Sunday/holiday | Sundays and public holidays |
| 3 | Saturday | All other Saturdays, including during school vacations |
| 2 | Vacation weekday | All other Mon–Fri during school vacations |
| 0 | Normal weekday | All other Tue–Thu |
| 1 | Weekday | All other Mon and Fri |

Code 1 only marks the days left over after codes 0 and 2. As a class, weekday means codes 0, 1 and 2 together:

```text
Weekday (Mon–Fri, not a public holiday)
├── Normal weekday (0): Tue–Thu outside school vacations
├── Other weekday (1): Mon and Fri outside school vacations
└── Vacation weekday (2): Mon–Fri during school vacations
Saturday (3)
Sunday/holiday (4)
```

Gap days (Brückentage) aren't a separate type. Buß- und Bettag doesn't count as a school holiday, so it's a normal weekday.

## Where the day types are used

| Step | Groups | Why |
|---|---|---|
| Scaling reference (annual cycle, vehicle share correction, SQV validation) | Code 0 only | Normal weekdays represent the average weekday traffic of the traffic model |
| Hourly profiles | Weekday (0, 1, 2), Saturday, Sunday/holiday (`DAY_GROUPS`) | One profile per class, month and vehicle class |
| Gap filling | Same as hourly profiles (`DAY_GROUPS`) | Fills missing days from days of the same class |
| Outlier checks | Weekday (0, 1), vacation weekday (2), Saturday, Sunday/holiday (`OUTLIER_GROUPS`) | Low traffic during a vacation is real, not a measurement error |

Daily volumes come from each actual date, so day types have only a small effect on annual totals.

## Data source

- **Public holidays:** categories `public` and `catholic` of the [`holidays`](https://pypi.org/project/holidays/) package for Bavaria (`DE`, `BY`). `catholic` adds Mariä Himmelfahrt, which is a holiday in Munich but not in all of Bavaria.
- **School holidays:** category `school` of the same package.
- **Overrides:** `data/auxiliary/calendar_overrides_munich.csv` corrects school holidays that changed after they were planned. There are 7 entries:
  - 21–22 December 2020: Christmas vacation brought forward in the pandemic.
  - 15–19 February 2021: Faschingsferien cancelled.

Pandemic school closures outside these changes are not treated as vacation.

## Module

| File | Purpose |
|---|---|
| `drive/io/calendar_holidays.py` | Reads the package and the override file |
| `drive/domain/calendar.py` | Holds the rules and groups (`classify_days`, `DAY_GROUPS`, `OUTLIER_GROUPS`), builds the calendar and checks stored calendars |
| `drive/schemas.py` | `CALENDAR`: the contract of the stored table |
| `drive/store.py` | `read_calendar` reads the latest batch of a region as a whole snapshot |
| `drive/pipeline.py` | `load_day_types` gives the pipeline its day types |
| `scripts/compare_v1_calendar.py` | Checks the rules, the store and the differences from the v1 workbook |

The store holds one row per day with `date`, `day_of_week`, `day_type`, `public_holiday`, `school_holiday` and `override` (the reason for a correction).

### Commands

The years and region are set under `ingest.calendar` in the config.

```bash
uv run drive ingest calendar configs/munich_2025.yaml
uv run python scripts/compare_v1_calendar.py configs/munich_2025.yaml
```

The ingest writes a new batch only if the generated calendar differs from the latest one. Re-run it after updating `holidays`, changing the overrides or extending the years.

### Errors that stop a run

- A year without complete school holidays in the package. `holidays` 0.108 is complete up to 2028 for Bavaria.
- An override that no longer changes anything, or a date listed twice. Review the entry after a package update.
- A stored calendar with missing days or weekdays that don't match its dates.
- A stored day type that differs from the current rules. Re-run the ingest after changing `classify_days`.
- A calendar that doesn't cover the counts period and the run.

## Differences from v1

v1 read its day types from `data/auxiliary/calender_18to26.xlsx`. It had a separate class for vacation weekdays and gap days, with its own hourly profile and outlier group. The workbook now serves only for comparisons. The comparison scripts set `run.calendar_source: v1_workbook`, which restores v1's day types and groups.

The workbook differs from the store on 25 of 3,287 days from 2018 to 2026, and `compare_v1_calendar.py` fails on any other difference:

| Days | Reason |
|---|---|
| 11 | Vacation days coded as normal days, although their description names the vacation |
| 5 | A false second Herbstferien week, 27–31 October 2025 (official dates: 3–7 November) |
| 3 | Public holidays not coded as holidays (3 October 2018, Fronleichnam 2022, 6 January 2023) |
| 3 | Gap days inside a school vacation |
| 3 | Buß- und Bettag coded as vacation (2024–2026) |

Hot emissions of 2025 compared with the same code on v1 day types:

| CO2(rep) | NOx | CO | PM10-ex | PM10-nx |
|---|---|---|---|---|
| −0.06 % | −0.05 % | −0.06 % | −0.12 % | +0.03 % |

## Known limitation

Weekdays around Christmas and New Year get the weekday profile, although their morning peak is lower. In 2025 the share of daily traffic at 07–09 h on vacation weekdays in January and December was about 8.3 %, against about 13 % in the weekday profile. There is no separate treatment yet (backlog item in the v2 spec).
