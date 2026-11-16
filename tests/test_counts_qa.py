"""Known-answer tests of the counts QA. All counts are invented."""

import numpy as np
import pandas as pd

from drive.domain.counts_qa import QAParams, _drop_share_outliers, link_volumes
from drive.schemas import HOURS

ROAD = 'Motorway-Nat'


def test_share_check_removes_only_the_faulty_class_and_year():
    """Six links count 10-12 % LCV; link 6 counts 30 % in 2024 and 11 % in 2025.

    Only link 6's LCV rows of 2024 may go: not its SUM, not its 2025 rows, not the other links.
    This would catch a key mix-up (wrong year or class removed) or a check that drops whole links.
    """
    dates = pd.date_range('2024-12-01', '2025-01-30')  # 31 days in 2024, 30 in 2025
    lcv_share = {1: 0.10, 2: 0.11, 3: 0.12, 4: 0.105, 5: 0.115, 6: 0.30}
    rows = []
    for link, share in lcv_share.items():
        for date in dates:
            lcv = share if link != 6 or date.year == 2024 else 0.11
            rows += [(link, 'SUM', date, 1000.0), (link, 'LCV', date, 1000.0 * lcv)]
    volume = pd.DataFrame(rows, columns=['road_link_id', 'vehicle_class', 'date', 'daily_value'])
    volume['scaling_road_type'] = ROAD
    params = QAParams(reference_year=2025, reference_day_type=0, completeness_window=('2025-01-01', '2025-12-31'),
                      share_check_classes=('LCV',))

    kept, flagged = _drop_share_outliers(volume, params)

    assert flagged[['road_link_id', 'year', 'vehicle_class']].values.tolist() == [[6, 2024, 'LCV']]
    # median of six log shares: the mean of the middle two, 0.11 and 0.115
    assert np.isclose(flagged['ratio_to_median'].iloc[0], 0.30 / np.sqrt(0.11 * 0.115))
    removed = volume.loc[~volume.index.isin(kept.index)]
    assert len(removed) == 31
    assert (removed['road_link_id'] == 6).all() and (removed['vehicle_class'] == 'LCV').all()
    assert (removed['date'].dt.year == 2024).all()


def test_incomplete_link_days_are_dropped_not_summed_as_zero():
    """One link counted by two detectors (both directions), 100 vehicles per hour each (D28).

    Day 1 complete -> 4800. Day 2: detector B has a missing hour (flag 'a', value 0, as BASt delivers it).
    Day 3: detector B has no row. v1 summed both as 4700 and 2400, i.e. too low; they must be dropped.
    Day 4: detector B's hour is an estimate ('s'), which is kept.
    """
    def row(detector, date, flags='-' * 24, missing_hour=False):
        hours = [100.0] * 24
        if missing_hour:
            hours[7] = 0.0
        return {'source': 'BASt', 'detector_id': detector, 'detector_type': None, 'date': pd.Timestamp(date),
                'vehicle_class': 'SUM', 'metric': 'volume', 'daily_value': sum(hours),
                **dict(zip(HOURS, hours)), 'flags': flags}

    a_flag = '-' * 7 + 'a' + '-' * 16
    s_flag = '-' * 7 + 's' + '-' * 16
    raw = pd.DataFrame([row('A', '2025-03-04'), row('B', '2025-03-04'),
                        row('A', '2025-03-05'), row('B', '2025-03-05', a_flag, missing_hour=True),
                        row('A', '2025-03-06'),
                        row('A', '2025-03-07'), row('B', '2025-03-07', s_flag)])
    raw['date'] = raw['date'].astype('datetime64[us]')
    links = pd.DataFrame({'source': 'BASt', 'detector_id': ['A', 'B'], 'traffic_model': 'visum2025', 'road_link_id': 1})
    attributes = pd.DataFrame({'road_type': [ROAD], 'road_type_ambiguous': [False]}, index=pd.Index([1]))
    day_types = pd.Series(0, index=pd.date_range('2025-03-04', '2025-03-07'))

    volume, dropped = link_volumes(raw, links, attributes, day_types, ('a', 'd', 'x'), drop_incomplete_days=True)

    assert dict(zip(volume['date'].dt.day, volume['daily_value'])) == {4: 4800.0, 7: 4800.0}
    assert dropped == 2
