"""Public and school holidays of a region from the `holidays` package, and the override file."""

from datetime import date
from pathlib import Path

import holidays
import pandas as pd
from holidays.constants import SCHOOL


def read_holidays(country: str,
                  subdivision: str,
                  years: list[int],
                  public_categories: list[str]) -> tuple[dict[date, str], dict[date, str]]:
    """Public and school holidays with their German names.

    Raises:
        ValueError: if the package has no complete school holidays for one of the years
    """
    public, school = (dict(holidays.country_holidays(country, subdiv=subdivision, years=years,
                                                     categories=tuple(categories), language='de'))
                      for categories in (public_categories, [SCHOOL]))
    # Without this check, years past the end of the package's tables turn vacation days into normal weekdays.
    # The tables can end within a year, so look for the Christmas vacation.
    complete = {d.year for d in school if d.month == 12}
    missing = sorted(set(years) - complete)
    if missing:
        raise ValueError(f'holidays {holidays.__version__} has no complete school holidays '
                         f'of {country}-{subdivision} for {missing}')
    return public, school


def read_overrides(path: str | Path) -> pd.DataFrame:
    """Reads corrections of the school holidays: date, school_holiday (empty = no vacation), reason.

    Raises:
        ValueError: if a date or reason is empty
    """
    overrides = pd.read_csv(path, parse_dates=['date'], usecols=['date', 'school_holiday', 'reason'])
    overrides['date'] = overrides['date'].astype('datetime64[us]')
    if overrides[['date', 'reason']].isna().any(axis=None):
        raise ValueError(f'{path} has a row without date or reason')
    return overrides
