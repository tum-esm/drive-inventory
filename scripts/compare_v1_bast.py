"""Compare the BASt station-table reader (drive/io/bast.py) with v1's preprocessed counts in the store.

Usage: uv run python scripts/compare_v1_bast.py [configs/munich_2025.yaml]

Reads v1's merged station tables (BAST_CountingStations_daily_2018.csv, BAST_TrafficCounts_raw.csv) and
compares every detector, day and class with the interim ingest of v1's preprocessed file. Expected:
hours without a row are missing here and 0 in v1 (same link sums). Every other difference is listed.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from drive import store
from drive.config import load_config
from drive.io import bast
from drive.schemas import COUNT_KEY, HOURS

FILES = ['BAST_CountingStations_daily_2018.csv', 'BAST_TrafficCounts_raw.csv']
FOLDER = Path('restricted_input/counting_data/bast')


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    config = load_config(config_path)
    batches = store.read_batches(config.paths.store)
    interim = batches[(batches['kind'] == 'counts') & (batches['source'] == 'BASt') & (batches['params'] != '{}')]
    version = int(interim['batch_id'].max())
    v1 = store.read_counts(config.paths.store, version)
    v1 = v1[v1['source'] == 'BASt'].drop(columns=['batch_id', 'flags'], errors='ignore')
    v1['date'] = v1['date'].astype('datetime64[us]')
    print(f'v1 preprocessed (batch {version}): {len(v1)} rows, {v1["detector_id"].nunique()} detectors, '
          f'{v1["date"].min().date()} to {v1["date"].max().date()}')

    parts = []
    for name in FILES:
        counts, r = bast.read_station_table(config.paths.data_root / FOLDER / name)
        print(f'{name}: {len(counts)} rows, {r.stations} stations, {r.first_date} to {r.last_date}, '
              f'{r.hours_missing} station-hours without a row; KFZ flags {r.flags}')
        parts.append(counts)
    v2 = pd.concat(parts, ignore_index=True)

    merged = v1.merge(v2, on=COUNT_KEY, how='outer', suffixes=('_v1', '_v2'), indicator=True)
    print(f'rows only in v1 {(merged["_merge"] == "left_only").sum()}, only in v2 {(merged["_merge"] == "right_only").sum()}')
    both = merged[merged['_merge'] == 'both']
    a = both[[f'{h}_v1' for h in HOURS]].to_numpy(dtype=float)
    b = both[[f'{h}_v2' for h in HOURS]].to_numpy(dtype=float)
    same = (a == b) | (np.isnan(a) & np.isnan(b))
    missing_here = np.isnan(b) & ~same
    print(f'hourly values: {same.sum()} equal, {missing_here.sum()} missing here ({np.unique(a[missing_here])[:10]} in v1), '
          f'{(~same & ~missing_here).sum()} other differences')
    other = ~same & ~missing_here
    if other.any():
        rows = both[other.any(axis=1)]
        print(rows[['detector_id', 'date', 'vehicle_class']].assign(
            v1=list(a[other.any(axis=1)]), v2=list(b[other.any(axis=1)])).head(8).to_string())
        values = pd.Series(a[other]).value_counts().head(8)
        print(f'v1 values where they differ: {values.to_dict()}')
    daily = (both['daily_value_v1'] - both['daily_value_v2']).abs()
    print(f'daily values: max |diff| {daily.max()}; differ in {(daily > 0).sum()} rows')
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
