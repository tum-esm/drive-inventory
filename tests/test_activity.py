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


def test_pooled_bus_and_mot_shares_keep_the_other_classes_per_road_type():
    """Two city road types and a motorway, one link each, with BUS and MOT pooled over the city roads (D30).

    City A (1000 vehicles): PC 0.80, LCV 0.10, HGV 0.06, MOT 0.02, BUS 0.02.
    City B (1000 vehicles): PC 0.86, LCV 0.10, HGV 0.02, MOT 0.01, BUS 0.01.
    Motorway: PC 0.70, LCV 0.10, HGV 0.18, MOT 0.01, BUS 0.01 (not pooled).
    Pool medians: BUS and MOT 15 each, PC 830, LCV 100, HGV 40, sum 1000 -> pooled BUS = MOT = 0.015.
    A's other classes keep their ratios and fill 0.97: PC 0.80 x 0.97 / 0.96, and so on.
    Catches pooled values landing on the wrong road type and shares that no longer add up to 1.
    """
    dates = pd.date_range('2025-01-06', '2025-01-19', unit='us')
    day_types = pd.Series(classify_days(dates.day_of_week.to_numpy(), np.zeros(len(dates), bool),
                                        np.zeros(len(dates), bool)), index=dates.rename('date'))
    roads = {1: ('City A', {'PC': 0.80, 'LCV': 0.10, 'HGV': 0.06, 'MOT': 0.02, 'BUS': 0.02}),
             2: ('City B', {'PC': 0.86, 'LCV': 0.10, 'HGV': 0.02, 'MOT': 0.01, 'BUS': 0.01}),
             3: ('Motorway', {'PC': 0.70, 'LCV': 0.10, 'HGV': 0.18, 'MOT': 0.01, 'BUS': 0.01})}
    rows = []
    for link, (road, shares) in roads.items():
        for date, day_type in day_types.items():
            for vehicle_class, share in {**shares, 'SUM': 1.0}.items():
                daily = 1000.0 * share
                rows.append({'road_link_id': link, 'vehicle_class': vehicle_class, 'date': date,
                             'scaling_road_type': road, 'day_type': int(day_type), 'valid': True,
                             'complete': True, 'daily_value': daily, **{h: daily / 24 for h in HOURS}})
    activity = Activity(pd.DataFrame(rows), day_types, reference_year=2025, reference_day_type=0,
                        share_pools=[(['BUS', 'MOT'], ['City A', 'City B'])])

    shares = activity.get_vehicle_share('2025-01-15')
    scale = 0.97 / 0.96
    assert shares.loc['City A'].to_dict() == pytest.approx(
        {'PC': 0.80 * scale, 'LCV': 0.10 * scale, 'HGV': 0.06 * scale, 'MOT': 0.015, 'BUS': 0.015})
    assert shares.loc['City B', ['MOT', 'BUS']].to_list() == pytest.approx([0.015, 0.015])
    assert shares.loc['Motorway'].to_dict() == pytest.approx(roads[3][1])
    assert shares.sum(axis=1).to_list() == pytest.approx([1.0, 1.0, 1.0])
