"""Known-answer test of the daily scaling in domain.activity. All counts are invented."""

import numpy as np
import pandas as pd
import pytest

from drive.domain.activity import Activity
from drive.domain.calendar import classify_days
from drive.schemas import HOURS

ROAD = 'Distributor/Secondary'
SHARES = {'PC': 0.80, 'LCV': 0.10, 'HGV': 0.06, 'MOT': 0.02, 'BUS': 0.02}


def test_daily_scaling_is_relative_to_normal_weekdays_of_the_reference_year():
    """Three links that differ only in their level: 1000, 2000 and 6000 vehicles on normal weekdays of 2025.

    Every link counts 90 % of its level on the days of 2024 and 60 % on Saturdays and Sundays.
    Each link is divided by its own mean on normal weekdays of the reference year, so with
    reference year 2025 the daily factor is 1.0 on normal weekdays of 2025, 0.9 on those of 2024,
    and 0.6 on a Saturday of 2025.

    Catches scaling relative to the wrong year or day type (with reference year 2024, a 2025
    normal weekday would get 1/0.9), and a lost per-link normalisation: dividing by the mean of
    all links (3000) would give factors of 0.33, 0.67 and 2.0 per link and a median of 0.67.
    """
    dates = pd.date_range('2024-12-02', '2025-01-26', unit='us')
    # no holidays in this invented calendar, so every Tue-Thu is a normal weekday
    day_types = pd.Series(classify_days(dates.day_of_week.to_numpy(), np.zeros(len(dates), bool),
                                        np.zeros(len(dates), bool)), index=dates.rename('date'))

    rows = []
    for link, level in [(1, 1000.0), (2, 2000.0), (3, 6000.0)]:
        for date, day_type in day_types.items():
            total = level * (0.6 if day_type >= 3 else 0.9 if date.year == 2024 else 1.0)
            for vehicle_class, share in {**SHARES, 'SUM': 1.0}.items():
                daily = total * share
                rows.append({'road_link_id': link, 'vehicle_class': vehicle_class, 'date': date,
                             'scaling_road_type': ROAD, 'day_type': int(day_type), 'valid': True,
                             'complete': True, 'daily_value': daily, **{h: daily / 24 for h in HOURS}})
    activity = Activity(pd.DataFrame(rows), day_types, reference_year=2025, reference_day_type=0)

    factor = {day: activity.get_daily_scaling_factors(day)[ROAD]
              for day in ['2025-01-15', '2024-12-11', '2025-01-18']}
    assert factor == pytest.approx({'2025-01-15': 1.0, '2024-12-11': 0.9, '2025-01-18': 0.6})
    assert activity.get_vehicle_share('2025-01-15').loc[ROAD].to_dict() == pytest.approx(SHARES)
