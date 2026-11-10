"""Day types used for traffic scaling, derived from public and school holidays.

Every day has exactly one `day_type`, the most specific class it belongs to. The first rule that matches wins:

    4 Sunday/holiday    Sundays and public holidays
    3 Saturday          other Saturdays, also during school vacation
    2 vacation weekday  other Mon-Fri during school vacation
    0 normal weekday    other Tue-Thu
    1 weekday           other Mon and Fri

The classes are nested, see DAY_GROUPS: weekday contains the normal weekdays and the vacation
weekdays. Normal weekdays alone are the reference of the scaling; hourly profiles and gap filling
use the groups. Outlier checks keep vacation weekdays apart, see OUTLIER_GROUPS.
"""

from collections.abc import Mapping
from datetime import date

import numpy as np
import pandas as pd

from drive.schemas import CALENDAR

NORM_WEEKDAY, WEEKDAY, VACATION_WEEKDAY, SATURDAY, SUNDAY_HOLIDAY = 0, 1, 2, 3, 4

# day type -> class of its hourly profile and gap filling
DAY_GROUPS = {NORM_WEEKDAY: WEEKDAY, WEEKDAY: WEEKDAY, VACATION_WEEKDAY: WEEKDAY,
              SATURDAY: SATURDAY, SUNDAY_HOLIDAY: SUNDAY_HOLIDAY}
# day type -> group of its outlier check: low traffic in a vacation is not an error
OUTLIER_GROUPS = {**DAY_GROUPS, VACATION_WEEKDAY: VACATION_WEEKDAY}


def classify_days(day_of_week: np.ndarray, is_public: np.ndarray, is_school: np.ndarray) -> np.ndarray:
    """Day type per day, see the module docstring. day_of_week: 0=Mon..6=Sun."""
    return np.select([is_public | (day_of_week == 6),
                      day_of_week == 5,
                      is_school,
                      (day_of_week >= 1) & (day_of_week <= 3)],
                     [SUNDAY_HOLIDAY, SATURDAY, VACATION_WEEKDAY, NORM_WEEKDAY], default=WEEKDAY)


def group_day_types(day_types: pd.Series, groups: Mapping[int, int] | None) -> pd.Series:
    """Replaces day types by their group; None keeps every day type as its own group (v1).

    Raises:
        ValueError: for a day type without group, which would silently drop its days
    """
    if groups is None:
        return day_types
    unknown = set(day_types.unique()) - set(groups)
    if unknown:
        raise ValueError(f'Day types {sorted(unknown)} have no group')
    return day_types.map(groups).astype(day_types.dtype)


def build_calendar(region: str,
                   years: list[int],
                   public: Mapping[date, str],
                   school: Mapping[date, str],
                   overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """Calendar per day (contract drive.schemas.CALENDAR) from holiday tables.

    Args:
        public, school: holiday name per date, may reach beyond `years`
        overrides: corrections of the school holidays, columns date, school_holiday (empty =
            no vacation), reason; dates outside `years` are ignored

    Raises:
        ValueError: for duplicate overrides, and for overrides that change nothing, which
            means that the holiday tables have changed and the entry needs a review
    """
    dates = pd.date_range(f'{min(years)}-01-01', f'{max(years)}-12-31', freq='D', unit='us')
    calendar = pd.DataFrame({
        'region': region,
        'date': dates,
        'day_of_week': dates.dayofweek.to_numpy().astype('int64'),
        'day_type': 0,
        'public_holiday': pd.Series([public.get(d.date()) for d in dates], dtype=object),
        'school_holiday': pd.Series([school.get(d.date()) for d in dates], dtype=object),
        'override': pd.Series([None] * len(dates), dtype=object),
    })

    if overrides is not None:
        selected = overrides[overrides['date'].isin(dates)]
        if selected['date'].duplicated().any():
            raise ValueError('Duplicate dates in the calendar overrides')
        positions = dates.get_indexer(pd.DatetimeIndex(selected['date']))
        current = calendar['school_holiday'].to_numpy()[positions]
        for day, new, name in zip(pd.DatetimeIndex(selected['date']), selected['school_holiday'], current):
            if (pd.isna(new) and pd.isna(name)) or new == name:
                raise ValueError(f'The calendar override of {day.date()} changes nothing, review it')
        names = selected['school_holiday'].astype(object).where(selected['school_holiday'].notna(), None)
        # pandas-stubs has no overload for a position array with a column position
        calendar.iloc[positions, calendar.columns.get_loc('school_holiday')] = names.to_numpy()  # pyright: ignore[reportCallIssue, reportArgumentType]
        calendar.iloc[positions, calendar.columns.get_loc('override')] = selected['reason'].to_numpy()  # pyright: ignore[reportCallIssue, reportArgumentType]

    calendar['day_type'] = classify_days(calendar['day_of_week'].to_numpy(), calendar['public_holiday'].notna().to_numpy(),
                                         calendar['school_holiday'].notna().to_numpy())
    return CALENDAR.validate(calendar)


def calendar_day_types(calendar: pd.DataFrame) -> pd.Series:
    """Checks a stored calendar and returns its day type per date.

    Raises:
        ValueError: if the dates aren't whole consecutive years, or if a stored value differs
            from what the rules give, e.g. for a batch ingested under older rules
    """
    dates = pd.DatetimeIndex(calendar['date'])
    expected = pd.date_range(f'{dates.min().year}-01-01', f'{dates.max().year}-12-31', freq='D')
    if not dates.equals(expected.as_unit(dates.unit)):
        raise ValueError(f'The calendar must have every day of whole years, got {dates.min()} to {dates.max()} '
                         f'with {len(dates)} days')
    day_of_week = calendar['day_of_week'].to_numpy()
    if (day_of_week != dates.dayofweek.to_numpy()).any():
        raise ValueError('The calendar has wrong weekdays')
    derived = classify_days(day_of_week, calendar['public_holiday'].notna().to_numpy(),
                            calendar['school_holiday'].notna().to_numpy())
    wrong = (derived != calendar['day_type'].to_numpy()).sum()
    if wrong:
        raise ValueError(f'{wrong} stored day types differ from the rules, run `drive ingest calendar`')
    return pd.Series(calendar['day_type'].to_numpy().astype('int64'), index=dates.rename('date'), name='day_type')


def combined_day_types(calendar: pd.DataFrame) -> pd.Series:
    """v1's day types from v1's workbook, only for comparisons with v1.

    Port of v1 excel_calendar.Calendar.get_day_type_combined: 0 normweekday (Tue-Thu weekday),
    1 weekday, 2 weekday during vacation or gap day, 3 Saturday, 4 Sunday or holiday.

    Args:
        calendar: columns date, day_of_week (0=Mon..6=Sun), day_type (workbook code:
            1 weekday, 2 weekend, 3 holiday, 4 gap day, 5 vacation day)

    Returns:
        pd.Series: day type indexed by date

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
