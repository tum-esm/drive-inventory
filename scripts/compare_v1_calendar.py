"""Check the calendar in the store: the rules, the package and v1's workbook.

Usage: uv run python scripts/compare_v1_calendar.py [configs/munich_2025.yaml]

1. Truth table: every combination of weekday, public holiday and school vacation falls in
   exactly the class the hierarchy says. The expected classes are written out separately from
   the code they check, and each class is checked for its nested membership.
2. Store: rebuilt from the package and the overrides, it must equal the stored calendar. Lists
   what the overrides change.
3. Workbook: its codes under the same rules must differ from the store only on the listed
   dates. A new difference fails, and so does a listed date that no longer differs.
   Names are not compared: the workbook spells the same holiday in several ways.
"""

import sys
from itertools import product

import numpy as np
import pandas as pd

from drive import store
from drive.config import load_config
from drive.domain.calendar import (
    DAY_GROUPS,
    NORM_WEEKDAY,
    OUTLIER_GROUPS,
    SATURDAY,
    SUNDAY_HOLIDAY,
    VACATION_WEEKDAY,
    WEEKDAY,
    build_calendar,
    calendar_day_types,
    classify_days,
)
from drive.io.calendar_excel import read_calendar
from drive.io.calendar_holidays import read_holidays, read_overrides
from drive.schemas import CALENDAR

NAMES = {NORM_WEEKDAY: 'normal weekday', WEEKDAY: 'weekday', VACATION_WEEKDAY: 'vacation weekday', SATURDAY: 'Saturday',
         SUNDAY_HOLIDAY: 'Sunday/holiday'}

_VACATION_AS_WEEKDAY = 'workbook: vacation day coded as a normal day, its description names the vacation'
_GAP_IN_VACATION = 'workbook: gap day inside a school vacation'
_HOLIDAY_NOT_CODED = 'workbook: public holiday not coded as holiday, its description names the holiday'
_FALSE_VACATION = 'workbook: false second Herbstferien week, official dates are 3-7 November 2025'
_BUSS_UND_BETTAG = 'workbook: Buss- und Bettag as vacation, not a school holiday by decision of the author'
EXPECTED = {
    **dict.fromkeys(['2019-06-17', '2019-06-18', '2019-06-19', '2023-10-30', '2023-10-31', '2023-11-02', '2023-11-03',
                     '2024-09-09', '2024-12-27', '2024-12-30', '2024-12-31'], _VACATION_AS_WEEKDAY),
    **dict.fromkeys(['2019-06-21', '2024-05-31', '2024-08-16'], _GAP_IN_VACATION),
    **dict.fromkeys(['2018-10-03', '2022-06-16', '2023-01-06'], _HOLIDAY_NOT_CODED),
    **dict.fromkeys(['2025-10-27', '2025-10-28', '2025-10-29', '2025-10-30', '2025-10-31'], _FALSE_VACATION),
    **dict.fromkeys(['2024-11-20', '2025-11-19', '2026-11-18'], _BUSS_UND_BETTAG),
}


def expected_class(day_of_week: int, public: bool, school: bool) -> int:
    if day_of_week == 6 or public:
        return SUNDAY_HOLIDAY
    if day_of_week == 5:
        return SATURDAY
    if school:
        return VACATION_WEEKDAY
    return NORM_WEEKDAY if day_of_week in (1, 2, 3) else WEEKDAY


def check_truth_table() -> bool:
    cases = np.array(list(product(range(7), [False, True], [False, True])))
    derived = classify_days(cases[:, 0], cases[:, 1].astype(bool), cases[:, 2].astype(bool))
    expected = np.array([expected_class(int(d), bool(p), bool(s)) for d, p, s in cases])
    wrong = (derived != expected).sum()
    print(f'Truth table: {wrong} of {len(cases)} combinations wrong')
    nested = (DAY_GROUPS == {NORM_WEEKDAY: WEEKDAY, WEEKDAY: WEEKDAY, VACATION_WEEKDAY: WEEKDAY,
                             SATURDAY: SATURDAY, SUNDAY_HOLIDAY: SUNDAY_HOLIDAY}
              and OUTLIER_GROUPS == {**DAY_GROUPS, VACATION_WEEKDAY: VACATION_WEEKDAY}
              and set(DAY_GROUPS) == set(NAMES))
    print(f'Nested classes: {"as specified" if nested else "WRONG"}')
    return wrong == 0 and nested


def check_rebuild(c, region: str, years: list[int], stored: pd.DataFrame) -> bool:
    public, school = read_holidays(c.country, c.subdivision, years, c.public_categories)
    rebuilt = build_calendar(region, years, public, school, read_overrides(c.overrides))
    package = build_calendar(region, years, public, school)
    columns = list(CALENDAR.columns)
    same = rebuilt[columns].astype(object).where(rebuilt[columns].notna(), None) \
        .equals(stored[columns].astype(object).where(stored[columns].notna(), None))
    print(f'Rebuilt from the package and the overrides: {"same" if same else "DIFFERENT"} as the store')
    changed = (package['day_type'].to_numpy() != stored['day_type'].to_numpy())
    print(f'The overrides change {changed.sum()} day types of {len(stored)} days:')
    table = pd.DataFrame({'date': stored['date'][changed].dt.date,
                          'package': package['day_type'][changed].map(NAMES),
                          'store': stored['day_type'][changed].map(NAMES)})
    print(table.to_string(index=False))
    return same


def check_workbook(config, years: list[int], stored: pd.DataFrame) -> bool:
    workbook = read_calendar(config.paths.calendar, years)
    if not stored['date'].equals(workbook['date']):
        print(f'Different dates: {len(stored)} days in the store, {len(workbook)} in the workbook')
        return False
    if (stored['day_of_week'].to_numpy() != workbook['day_of_week'].to_numpy()).any():
        print('Different weekdays')
        return False
    codes = workbook['day_type'].to_numpy()
    from_workbook = classify_days(workbook['day_of_week'].to_numpy(), codes == 3, codes == 5)
    day_types = stored['day_type'].to_numpy()
    different = from_workbook != day_types

    table = pd.DataFrame({'date': stored['date'][different].dt.strftime('%Y-%m-%d'),
                          'workbook': pd.Series(from_workbook[different], index=stored.index[different]).map(NAMES),
                          'store': stored['day_type'][different].map(NAMES)})
    table['explained_by'] = table['date'].map(EXPECTED)
    per_year = stored.assign(different=different).groupby(stored['date'].dt.year)['different'].sum()
    print(f'\nWorkbook under the same rules, differences per year: {per_year.to_dict()}')
    print(table.groupby('explained_by', dropna=False).size().to_string())
    unexplained = table[table['explained_by'].isna()]
    gone = sorted(set(EXPECTED) - set(table['date']))
    if len(unexplained) > 0:
        print(f'UNEXPLAINED:\n{unexplained.to_string(index=False)}')
    if gone:
        print(f'Listed but not different any more: {gone}')
    return unexplained.empty and not gone


def main(config_path: str) -> int:
    config = load_config(config_path)
    c = config.ingest.calendar
    years = list(range(c.years[0], c.years[1] + 1))
    region = f'{c.country}-{c.subdivision}'
    stored = store.read_calendar(config.paths.store, region, config.run.data_version)
    stored['date'] = stored['date'].astype('datetime64[us]')
    stored = stored.reset_index(drop=True)
    day_types = calendar_day_types(stored)

    counts = pd.crosstab(day_types.index.year, day_types.map(NAMES), rownames=['year'], colnames=[None])
    print(f'{region}, batch {stored["batch_id"].iloc[0]}:\n{counts.to_string()}\n')

    results = [check_truth_table(), check_rebuild(c, region, years, stored), check_workbook(config, years, stored)]
    print('\nOK' if all(results) else '\nFAILED')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml'))
