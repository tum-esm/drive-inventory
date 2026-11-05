"""Compare the v2 counts QA and Activity with v1.

Usage: uv run python scripts/compare_v1_counts.py [configs/munich_2025.yaml]

Activity is built from v1's combined file and compared with v1 TrafficCounts on the same
input. It must be identical; the rest of this docstring is about the counts QA, compared
with data_preprocessing/31 -> counting_data_combined.parquet.

v1's combined file was built from 2019-2025 counts, so v2 is run on the same period
(outlier detection uses all years at once). Expected differences:
- BASt missing-value markers (-1, 2019): v1 summed them as negative counts, v2 treats
  them as missing (0 in the link sum). Every difference must belong to a (link, vehicle
  class) with marker days; anything else is reported as unexplained.
- R3: v2 marks links without data in the completeness window as incomplete. The v1 rule
  is recomputed from v2's completeness to check that only this rule differs.
"""

import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt

from drive import store
from drive.config import load_config
from drive.domain.activity import Activity
from drive.domain.calendar import combined_day_types
from drive.io.calendar_excel import read_calendar
from drive.pipeline import load_link_counts
from drive.schemas import HOURS

V1_FILE = 'restricted_input/counting_data/counting_data_combined.parquet'
KEY = ['road_link_id', 'vehicle_class', 'date']
FLOAT_TOLERANCE = 1e-9


def load_v1(data_root: Path) -> pd.DataFrame:
    v1 = pd.read_parquet(data_root / V1_FILE)
    v1 = v1.rename(columns={str(h): f'h{h:02d}' for h in range(24)} | {'completness': 'completeness'})
    v1['road_link_id'] = v1['road_link_id'].astype('int64')
    v1['date'] = v1['date'].astype('datetime64[us]')
    return v1


def marker_link_classes(config) -> pd.DataFrame:
    """(road_link_id, vehicle_class) pairs with BASt missing-value markers in 2019-2025."""
    raw = store.read_counts(config.paths.store, config.run.data_version, metric='volume', start='2019-01-01')
    marked = raw[(raw['source'] == 'BASt') & raw[HOURS].isna().any(axis=1)]
    links = store.read_counter_links(config.paths.store, config.run.traffic_model, config.run.data_version)
    marked = marked.merge(links, on=['source', 'detector_id'])
    pairs = marked[['road_link_id', 'vehicle_class']].drop_duplicates()
    # the SUM of a link contains the marked classes as well
    return pd.concat([pairs, pairs.assign(vehicle_class='SUM')]).drop_duplicates()


def compare_link_counts(config) -> bool:
    config.counts_qa.period_start = date(2019, 1, 1)
    v2, report, version = load_link_counts(config)
    v1 = load_v1(config.paths.data_root)
    print(f'v2 at store batch {version}: {len(v2)} rows, v1: {len(v1)} rows')

    merged = v1.merge(v2, on=KEY, how='outer', suffixes=('_v1', '_v2'), indicator=True)
    differs = merged['_merge'] != 'both'
    both = merged['_merge'] == 'both'
    for col in ['road_type', 'scaling_road_type', 'day_type', 'valid']:
        differs |= both & (merged[f'{col}_v1'] != merged[f'{col}_v2'])
    for col in ['sqv', 'completeness', 'daily_value'] + HOURS:
        a, b = merged[f'{col}_v1'], merged[f'{col}_v2']
        differs |= both & ~np.isclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True)
    v1_rule = (merged['completeness_v2'] > config.counts_qa.completeness_threshold) | (merged['completeness_v2'] == 0)
    differs |= both & (merged['complete_v1'] != v1_rule)

    markers = marker_link_classes(config).assign(_marker=True)
    diff = merged[differs].merge(markers, on=['road_link_id', 'vehicle_class'], how='left')
    explained = diff['_marker'].fillna(False).astype(bool)

    print(f'\nRows that differ: {len(diff)} (only v1: {(diff["_merge"] == "left_only").sum()}, '
          f'only v2: {(diff["_merge"] == "right_only").sum()}, values: {(diff["_merge"] == "both").sum()})')
    print(f'  explained by BASt markers: {explained.sum()} rows on '
          f'{diff.loc[explained, "road_link_id"].nunique()} links')
    unexplained = diff[~explained]
    print(f'  unexplained: {len(unexplained)}')
    if len(unexplained):
        print(unexplained[KEY + ['_merge']].head(20).to_string(index=False))

    r3 = merged[both & (merged['complete_v1'] != merged['complete_v2'])]
    print(f'\nR3 (completeness 0 -> incomplete): {r3["road_link_id"].nunique()} links, {len(r3)} rows, '
          f'links {sorted(r3["road_link_id"].unique())}')
    print(f'  QA report: {report}')
    return len(unexplained) == 0


def _report(name: str, v2: pd.Series | pd.DataFrame, v1: pd.Series | pd.DataFrame) -> bool:
    """Compares v2 with v1 at float tolerance; index and column order are ignored."""
    try:
        compare = pdt.assert_frame_equal if isinstance(v2, pd.DataFrame) else pdt.assert_series_equal
        compare(v2, v1, rtol=FLOAT_TOLERANCE, atol=FLOAT_TOLERANCE, check_like=True, check_names=False,
                check_index_type=False, check_dtype=False, check_freq=False)
    except AssertionError as error:
        print(f'  {name}: DIFFERENT\n{error}')
        return False
    print(f'  {name}: identical ({len(v2)} rows, {int(v2.isna().sum().sum())} NaN)')
    return True


def compare_activity(config) -> bool:
    """Pure-port check: Activity and v1 TrafficCounts on the same input, v1's combined file."""
    sys.path.append(str(Path(__file__).resolve().parents[1] / 'utils'))
    from traffic_counts import TrafficCounts  # v1, flat import by convention

    v1_input = load_v1(config.paths.data_root)
    years = list(range(v1_input['date'].dt.year.min(), v1_input['date'].dt.year.max() + 1))
    day_types = combined_day_types(read_calendar(config.paths.calendar, years))

    start = time.perf_counter()
    v2 = Activity(v1_input, day_types, config.run.reference_year, config.run.reference_day_type)
    v2_seconds = time.perf_counter() - start
    start = time.perf_counter()
    v1 = TrafficCounts(reference_year=config.run.reference_year, reference_day_type=config.run.reference_day_type)
    print(f'Built Activity in {v2_seconds:.1f} s, TrafficCounts in {time.perf_counter() - start:.1f} s')

    v1_cycles = v1.daily_cycles.rename(columns={str(h): f'h{h:02d}' for h in range(24)})
    results = [_report('vehicle_shares', v2.vehicle_shares, v1.vehicle_shares),
               _report('annual_cycles', v2.annual_cycles, v1.annual_cycles),
               _report('daily_cycles', v2.daily_cycles.sort_index(), v1_cycles.sort_index())]
    results.append(set(v2.road_types) == set(v1.road_types))
    for road_type in v2.road_types:
        v1_profile = v1.timeprofile[road_type].rename_axis('time')
        results.append(_report(f'timeprofile {road_type}', v2.timeprofile[road_type], v1_profile))
        zero_v1 = v1_profile.resample('D').sum(min_count=1).eq(0).all(axis=1)
        missing = v2.missing_days[road_type]
        print(f'    missing_days: {len(missing)}, all-zero days in v1: {zero_v1.sum()}, '
              f'same days: {set(missing) == set(zero_v1[zero_v1].index)}')
    return all(results)


if __name__ == '__main__':
    config = load_config(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml')
    link_counts_ok = compare_link_counts(config)
    print('\nLINK COUNTS:', 'OK (only expected differences)' if link_counts_ok else 'UNEXPLAINED DIFFERENCES')
    print('\nActivity on v1 input vs TrafficCounts:')
    activity_ok = compare_activity(config)
    print('\nACTIVITY:', 'OK (identical)' if activity_ok else 'DIFFERENT')
    sys.exit(0 if link_counts_ok and activity_ok else 1)
