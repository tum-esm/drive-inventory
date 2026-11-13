"""Compare the BASt counts from `drive ingest bast` with v1's preprocessed counts, per year.

Usage: uv run python scripts/compare_bast_sources.py [configs/munich_2025.yaml]

v1's counts (interim batch 2, read here from v1's merged tables with their flags) came from the annual files for 2018-2022 and from v1's own parse of the raw data
for 2023 to January 2026. The new counts come from the annual files for every published year and from the raw
data after that. Per year: which product the new counts come from, how many detector-days and hourly values are
equal, and whether every difference comes with a changed flag (a revision by BASt). Differences without a
changed flag would point to a reading error. Also lists detector-days that only one side has.
"""

import sys

import numpy as np
import pandas as pd

from drive import store
from drive.config import load_config
from drive.io import bast as bast_io
from drive.schemas import COUNT_KEY, HOURS

FOLDER = 'restricted_input/counting_data/bast'
V1_FILES = ['BAST_CountingStations_daily_2018.csv', 'BAST_TrafficCounts_raw.csv']


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    config = load_config(config_path)
    path = config.paths.store
    batches = store.read_batches(path)
    bast = batches[(batches['kind'] == 'counts') & (batches['source'] == 'BASt')]
    interim = int(bast.loc[bast['params'].str.contains('traffic_models'), 'batch_id'].max())
    product = {int(b): ('annual' if '"annual"' in p else 'raw') for b, p in zip(bast['batch_id'], bast['params'])
               if b != interim}

    def load(version: int) -> pd.DataFrame:
        counts = store.read_counts(path, version)
        counts = counts[counts['source'] == 'BASt'].copy()
        counts['date'] = counts['date'].astype('datetime64[us]')
        return counts

    # v1's merged tables give the same values as the interim batch (compare_v1_bast.py) and keep the flags
    old = pd.concat([bast_io.read_station_table(config.paths.data_root / FOLDER / f)[0] for f in V1_FILES])
    new = load(int(batches['batch_id'].max()))
    still_interim = (new['batch_id'] == interim).sum()
    new = new[new['batch_id'] != interim]
    new['product'] = new['batch_id'].map(product)

    merged = old.merge(new, on=COUNT_KEY, how='outer', suffixes=('_v1', '_new'), indicator=True)
    merged['year'] = merged['date'].dt.year
    rows = []
    for year, group in merged.groupby('year'):
        both = group[group['_merge'] == 'both']
        a = both[[f'{h}_v1' for h in HOURS]].to_numpy(dtype=float)
        b = both[[f'{h}_new' for h in HOURS]].to_numpy(dtype=float)
        # v1 had 0 where the new counts have no value (hours without a row)
        same = (a == b) | (np.isnan(a) & np.isnan(b)) | ((a == 0) & np.isnan(b))
        flag_changed = (both['flags_v1'] != both['flags_new']).to_numpy()
        value_diff = ~same.all(axis=1)
        rows.append({
            'year': year,
            'product': ', '.join(sorted(group['product'].dropna().unique())),
            'only v1': int((group['_merge'] == 'left_only').sum()),
            'only new': int((group['_merge'] == 'right_only').sum()),
            'rows': len(both),
            'rows equal': int((~value_diff).sum()),
            'hours differ': int((~same).sum()),
            'flags differ': int(flag_changed.sum()),
            'rows differ, flags equal': int((value_diff & ~flag_changed).sum()),
        })
    print(f'v1 interim batch {interim}; new batches {sorted(product)}; rows still read from the interim batch: '
          f'{still_interim}')
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
