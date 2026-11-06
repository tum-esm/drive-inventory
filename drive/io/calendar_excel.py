"""Reader for the hand-maintained calendar workbook (data/auxiliary/calender_18to26.xlsx).

One sheet per year with columns `date, day_of_week (0=Mon..6=Sun), day_type`
(1 weekday, 2 weekend, 3 holiday, 4 gap day, 5 vacation day). Only used for comparisons with v1 since `drive ingest calendar` (R21).
"""

from pathlib import Path

import pandas as pd


def read_calendar(path: str | Path, years: list[int]) -> pd.DataFrame:
    """Reads the calendar sheets of the given years.

    Raises:
        ValueError: if a year has no sheet in the workbook
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
