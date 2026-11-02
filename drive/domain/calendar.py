"""Day types used for traffic scaling (port of v1 excel_calendar.Calendar.get_day_type_combined)."""

import numpy as np
import pandas as pd

# combined day types; normweekday is a subset of weekday in traffic engineering terms
NORM_WEEKDAY, WEEKDAY, VACATION_WEEKDAY, SATURDAY, SUNDAY_HOLIDAY = 0, 1, 2, 3, 4


def combined_day_types(calendar: pd.DataFrame) -> pd.Series:
    """Combined day type per date.

    0 normweekday (Tue-Thu weekday), 1 weekday, 2 weekday during vacation or gap day,
    3 Saturday, 4 Sunday or holiday (shops closed in Germany).

    Args:
        calendar: columns date, day_of_week (0=Mon..6=Sun), day_type (1..5, see io.calendar_excel)

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
