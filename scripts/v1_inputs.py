"""v1 inputs for the comparison scripts: v1's calendar workbook, boundary file and preprocessed counts.

v2 reads its day types, clip area and counts from the store only (`drive ingest calendar`, `drive ingest boundaries`,
`drive ingest lhm`, `drive ingest bast`).
The comparison scripts use v1's own inputs where they check a port against v1 on identical inputs.
"""

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from drive.domain.calendar import NORM_WEEKDAY, SATURDAY, SUNDAY_HOLIDAY, VACATION_WEEKDAY, WEEKDAY
from drive.schemas import COUNTER_LINKS, HOURS, RAW_COUNTS

CALENDAR = Path('auxiliary/calender_18to26.xlsx')  # relative to paths.data_root
BOUNDARY = Path('geodata/munich_boarders.gpkg')


def read_calendar(path: str | Path, years: list[int]) -> pd.DataFrame:
    """The calendar sheets of the given years: date, day_of_week (0=Mon..6=Sun), day_type
    (1 weekday, 2 weekend, 3 holiday, 4 gap day, 5 vacation day).

    Raises:
        ValueError: if a year has no sheet or a date appears twice
    """
    workbook = pd.ExcelFile(path)
    missing = [y for y in years if str(y) not in workbook.sheet_names]
    if missing:
        raise ValueError(f'{path} has no calendar sheet for {missing}')
    calendar = pd.concat([pd.read_excel(workbook, sheet_name=str(y), usecols=['date', 'day_of_week', 'day_type'])
                          for y in years], ignore_index=True)
    calendar['date'] = pd.to_datetime(calendar['date']).astype('datetime64[us]')
    if calendar['date'].duplicated().any():
        raise ValueError(f'{path} has duplicate dates')
    return calendar


def combined_day_types(calendar: pd.DataFrame) -> pd.Series:
    """v1's day types (port of v1 excel_calendar.Calendar.get_day_type_combined): 0 normweekday (Tue-Thu weekday),
    1 weekday, 2 weekday during vacation or gap day, 3 Saturday, 4 Sunday or holiday.

    Raises:
        ValueError: for day_type/day_of_week combinations that no rule covers
    """
    dt = calendar['day_type'].to_numpy()
    wd = calendar['day_of_week'].to_numpy()
    # the order of the rules matters, it follows v1
    conditions = [
        (dt == 1) & (wd >= 1) & (wd <= 3),
        dt == 1,
        (dt == 4) | (dt == 5),
        (dt == 2) & (wd == 5),
        (dt == 3) | (wd == 6),
    ]
    choices = [NORM_WEEKDAY, WEEKDAY, VACATION_WEEKDAY, SATURDAY, SUNDAY_HOLIDAY]
    combined = np.select(conditions, choices, default=-1)
    unknown = combined == -1
    if unknown.any():
        rows = calendar.loc[unknown, ['date', 'day_of_week', 'day_type']]
        raise ValueError(f'No day type rule for {len(rows)} dates:\n{rows.head()}')
    return pd.Series(combined, index=pd.DatetimeIndex(calendar['date'], name='date'), name='day_type')


def day_types(data_root: Path, years: list[int]) -> pd.Series:
    """v1's day types of the given years."""
    return combined_day_types(read_calendar(data_root / CALENDAR, years))


def boundary(data_root: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(data_root / BOUNDARY)


# ---- v1's preprocessed counts (data_preprocessing/11 and 12), formerly the interim `drive ingest counts` ----
# Files: BAST_/MST_TrafficCounts_preprocessed*.parquet with columns
# `date, road_link_id, detector_id, detector_type, vehicle_class, metric, daily_value, 0..23`.

_SOURCE_HOURS = [str(h) for h in range(24)]


@dataclass
class CountsIngestReport:
    rows: int = 0
    detectors: int = 0
    detectors_without_link: int = 0
    missing_marker_rows: int = 0
    links_missing_in_model: dict[str, list[int]] = field(default_factory=dict)


def read_preprocessed_counts(path: str | Path,
                             source: str,
                             model_link_ids: dict[str, set[int]]) -> tuple[pd.DataFrame, pd.DataFrame, CountsIngestReport]:
    """Reads one preprocessed counting data file.

    Args:
        path: parquet file
        source: 'BASt' or 'LHM'
        model_link_ids: traffic model -> road_link_ids of that model

    Returns:
        raw counts (RAW_COUNTS), counter links (COUNTER_LINKS) and a report
    """
    df = pd.read_parquet(path)
    report = CountsIngestReport(rows=len(df), detectors=df['detector_id'].nunique())

    # BASt marks missing hours with -1 (daily value = sum of the markers, e.g. -24)
    negative_hours = (df[_SOURCE_HOURS] < 0).any(axis=1)
    missing = negative_hours | (df['daily_value'] < 0)
    report.missing_marker_rows = int(missing.sum())
    hours = df[_SOURCE_HOURS].mask(df[_SOURCE_HOURS] < 0)
    daily = df['daily_value'].mask(missing)

    counts = pd.DataFrame({
        'source': source,
        'detector_id': df['detector_id'].astype(str),
        'detector_type': df['detector_type'],
        'date': df['date'].astype('datetime64[us]'),
        'vehicle_class': df['vehicle_class'],
        'metric': df['metric'],
        'daily_value': daily,
        **dict(zip(HOURS, (hours[h] for h in _SOURCE_HOURS))),
        'flags': None,
    })
    counts = RAW_COUNTS.validate(counts)

    pairs = df[['detector_id', 'road_link_id']].drop_duplicates()
    if pairs['detector_id'].duplicated().any():
        multi = pairs.loc[pairs['detector_id'].duplicated(keep=False), 'detector_id'].unique()
        raise ValueError(f'{path}: detectors matched to more than one link: {sorted(multi)[:10]}')
    report.detectors_without_link = int(pairs['road_link_id'].isna().sum())
    pairs = pairs.dropna(subset=['road_link_id'])
    pairs = pairs.assign(detector_id=pairs['detector_id'].astype(str),
                         road_link_id=pairs['road_link_id'].astype('int64'))

    links = []
    for model, link_ids in sorted(model_link_ids.items()):
        exists = pairs['road_link_id'].isin(link_ids)
        report.links_missing_in_model[model] = sorted(pairs.loc[~exists, 'road_link_id'].unique().tolist())
        links.append(pairs[exists].assign(source=source, traffic_model=model))
    columns = ['source', 'detector_id', 'traffic_model', 'road_link_id']
    links = COUNTER_LINKS.validate(pd.concat(links)[columns].reset_index(drop=True) if links else
                                   pd.DataFrame(columns=columns))

    return counts, links, report
