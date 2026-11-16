"""v1 inputs for the comparison scripts: v1's calendar workbook and boundary file.

v2 reads its day types and clip area from the store only (`drive ingest calendar`, `drive ingest boundaries`).
The comparison scripts use v1's own inputs where they check a port against v1 on identical inputs.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from drive.domain.calendar import NORM_WEEKDAY, SATURDAY, SUNDAY_HOLIDAY, VACATION_WEEKDAY, WEEKDAY

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
