"""Compare the LHM raw-export reader (drive/io/lhm.py) with v1's preprocessed counts.

Usage: uv run python scripts/compare_v1_lhm.py [configs/munich_2025.yaml]

For each export file, the counts of the detectors and dates in v1's preprocessed file
(MST_TrafficCounts_preprocessed_from2018.parquet) must be identical in every value. Expected differences:
detector_type (v1: '8+1' for all) and the daily value of speeds (v1: 0, now empty). Also compares the
counter links from the locations file with those in v1's file.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from drive.config import load_config
from drive.io import lhm
from drive.io.counts_preprocessed import read_preprocessed_counts
from drive.io.visum import read_links
from drive.schemas import COUNT_KEY, HOURS

COUNTS = Path('restricted_input/counting_data/lhm')
LOCATIONS = COUNTS / 'mst_locations_selected.gpkg'
V1_FILE = COUNTS / 'MST_TrafficCounts_preprocessed_from2018.parquet'


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    config = load_config(config_path)
    root = config.paths.data_root
    if config.visum is None:
        raise ValueError('The config needs the visum section')
    model_link_ids = {model: set(read_links(c.links, model, c.crs, c.link_columns, config.visum,
                                            config.scaling_road_types)[0]['road_link_id'])
                      for model, c in config.traffic_models.items()}
    v1, v1_links, _ = read_preprocessed_counts(root / V1_FILE, 'LHM', model_link_ids)
    v1 = v1.drop(columns='flags')
    print(f'v1 preprocessed: {len(v1)} rows, {v1["detector_id"].nunique()} detectors')

    failed, seen = False, []
    for file in sorted((root / COUNTS).glob('*_MST_Detektoren*.csv')):
        raw, report = lhm.read_export(file)
        own = raw[raw['detector_id'].isin(v1['detector_id'].unique())]
        old = v1[v1['date'].between(raw['date'].min(), raw['date'].max())]
        merged = old.merge(own, on=COUNT_KEY, how='outer', suffixes=('_v1', '_v2'), indicator=True)
        only_v1, only_v2 = (merged['_merge'] == 'left_only').sum(), (merged['_merge'] == 'right_only').sum()
        both = merged[merged['_merge'] == 'both']
        volume = both['metric'] == 'volume'
        columns = HOURS + ['daily_value']
        a = np.where(volume.to_numpy()[:, None], both[[f'{c}_v1' for c in columns]].to_numpy(dtype=float),
                     np.r_[both[[f'{h}_v1' for h in HOURS]].to_numpy(dtype=float).T, [np.zeros(len(both))]].T)
        b = np.where(volume.to_numpy()[:, None], both[[f'{c}_v2' for c in columns]].to_numpy(dtype=float),
                     np.r_[both[[f'{h}_v2' for h in HOURS]].to_numpy(dtype=float).T, [np.zeros(len(both))]].T)
        differ = ~((a == b) | (np.isnan(a) & np.isnan(b)))
        ok = only_v1 == 0 and only_v2 == 0 and not differ.any()
        failed |= not ok
        seen.append(raw['date'])
        print(f'{file.name}: {"identical" if ok else "DIFFERENT"}; {len(raw)} rows of {report.detectors} detectors, '
              f'{report.first_date} to {report.last_date}; only v1 {only_v1}, only v2 {only_v2}, values differ in '
              f'{differ.any(axis=1).sum()} rows; ARTs not read {report.unused_art}')

    dates = pd.concat(seen)
    uncovered = v1.loc[~v1['date'].isin(dates.unique()), 'date']
    print(f'v1 dates not in any export: {uncovered.nunique()}')
    failed |= len(uncovered) > 0

    links, missing = lhm.read_locations(root / LOCATIONS, model_link_ids)
    stored = v1_links
    key = ['detector_id', 'traffic_model']
    merged = links.merge(stored, on=key, how='outer', suffixes=('', '_stored'), indicator=True)
    extra = merged[merged['_merge'] == 'left_only']
    lost = merged[merged['_merge'] == 'right_only']
    moved = merged[(merged['_merge'] == 'both') & (merged['road_link_id'] != merged['road_link_id_stored'])]
    print(f'counter links: {len(links)} from the locations file, {len(stored)} in v1\'s file; only in the file '
          f'{extra["detector_id"].nunique()} detectors, only in v1 {lost["detector_id"].nunique()}, other link '
          f'{len(moved)}; links not in the model {missing}')
    failed |= len(lost) > 0 or len(moved) > 0
    print('OK' if not failed else 'FAILED')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
