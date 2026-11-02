"""Compare the v2 counts QA with v1 (data_preprocessing/31 -> counting_data_combined.parquet).

Usage: uv run python scripts/compare_v1_counts.py [configs/munich_2025.yaml]

v1's combined file was built from 2019-2025 counts, so v2 is run on the same period
(outlier detection uses all years at once). Expected differences:
- BASt missing-value markers (-1, 2019): v1 summed them as negative counts, v2 treats
  them as missing (0 in the link sum). Every difference must belong to a (link, vehicle
  class) with marker days; anything else is reported as unexplained.
- R3: v2 marks links without data in the completeness window as incomplete. The v1 rule
  is recomputed from v2's completeness to check that only this rule differs.
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from drive import store
from drive.config import load_config
from drive.pipeline import load_link_counts
from drive.schemas import HOURS

V1_FILE = 'restricted_input/counting_data/counting_data_combined.parquet'
KEY = ['road_link_id', 'vehicle_class', 'date']


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


if __name__ == '__main__':
    config = load_config(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml')
    ok = compare_link_counts(config)
    print('\nLINK COUNTS:', 'OK (only expected differences)' if ok else 'UNEXPLAINED DIFFERENCES')
    sys.exit(0 if ok else 1)
