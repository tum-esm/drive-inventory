"""Compare the LHM raw-export reader (drive/io/lhm.py) with v1's preprocessed counts in the store.

Usage: uv run python scripts/compare_v1_lhm.py [configs/munich_2025.yaml] [batch]

For each export file, the counts of the detectors and dates in v1's preprocessed file (batch: the
interim LHM ingest, see `drive ingest counts`) must be identical in every value. Expected differences:
detector_type (v1: '8+1' for all) and the daily value of speeds (v1: 0, now empty). Also compares the
counter links from the locations file with the stored ones.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from drive import store
from drive.config import load_config
from drive.io import lhm
from drive.io.visum import read_links
from drive.schemas import COUNT_KEY, HOURS

COUNTS = Path('restricted_input/counting_data/lhm')
LOCATIONS = COUNTS / 'mst_locations_selected.gpkg'


def main(config_path: str = 'configs/munich_2025.yaml', batch: str | None = None) -> int:
    config = load_config(config_path)
    root = config.paths.data_root
    batches = store.read_batches(config.paths.store)
    # the interim ingest of v1's preprocessed file stores counter links with the counts (params name the models)
    interim = batches[(batches['kind'] == 'counts') & (batches['source'] == 'LHM') & (batches['params'] != '{}')]
    version = int(batch) if batch else int(interim['batch_id'].max())
    v1 = store.read_counts(config.paths.store, version)
    v1 = v1[(v1['source'] == 'LHM') & (v1['batch_id'] <= version)].drop(columns='batch_id')
    v1['date'] = v1['date'].astype('datetime64[us]')
    print(f'v1 preprocessed (batch {version}): {len(v1)} rows, {v1["detector_id"].nunique()} detectors')

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

    model_link_ids = {}
    for model, c in config.traffic_models.items():
        if config.visum is None:
            raise ValueError('The config needs the visum section')
        model_link_ids[model] = set(read_links(c.links, model, c.crs, c.link_columns, config.visum,
                                               config.scaling_road_types)[0]['road_link_id'])
    links, missing = lhm.read_locations(root / LOCATIONS, model_link_ids)
    stored = pd.concat([store.read_counter_links(config.paths.store, m, version) for m in model_link_ids])
    stored = stored[stored['source'] == 'LHM'].drop(columns='batch_id')
    key = ['detector_id', 'traffic_model']
    merged = links.merge(stored, on=key, how='outer', suffixes=('', '_stored'), indicator=True)
    extra = merged[merged['_merge'] == 'left_only']
    lost = merged[merged['_merge'] == 'right_only']
    moved = merged[(merged['_merge'] == 'both') & (merged['road_link_id'] != merged['road_link_id_stored'])]
    print(f'counter links: {len(links)} from the locations file, {len(stored)} stored; only in the file '
          f'{extra["detector_id"].nunique()} detectors, only stored {lost["detector_id"].nunique()}, other link '
          f'{len(moved)}; links not in the model {missing}')
    failed |= len(lost) > 0 or len(moved) > 0
    print('OK' if not failed else 'FAILED')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
