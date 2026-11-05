"""Compare the emission factors in the store with the files and with v1's lookups.

Usage: uv run python scripts/compare_v1_ef.py [configs/munich_2025.yaml]

1. Every stored table holds the same values as its parquet file.
2. v1's hot and cold importers, run on the same files, give the same factors as the store.
   v1's hot lookup has no ambient pattern in its key, so `to_dict` keeps the last row per
   key. V1_HOT_PATTERN is the pattern that this selects. In the 2019 and 2020 tables it also
   selects the WTT row of CO2e, which is the only pollutant with two process scopes.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from drive import store
from drive.config import load_config
from drive.io import hbefa

V1_HOT_PATTERN = 'T+25°C,tØ,dØ'
TOLERANCE = dict(rtol=0.0, atol=0.0, equal_nan=True)
RAW_VALUES = {'Weight': 'weight', 'EFA': 'efa', 'EFA_0%': 'efa_0', 'EFA_100%': 'efa_100', 'v': 'speed', 'v_0%': 'speed_0',
              'v_100%': 'speed_100', 'Cum. mileage': 'cum_mileage'}


def _read(config, file: hbefa.EfFile) -> pd.DataFrame:
    return store.read_emission_factors(config.paths.store, file.hbefa_version, file.reference_year,
                                       file.emission_category, file.aggregation, data_version=config.run.data_version)


def check_against_file(config, file: hbefa.EfFile) -> bool:
    stored = _read(config, file)
    raw = pd.read_parquet(file.path)
    situation = 'Aggr. traffic situation' if 'Aggr. traffic situation' in raw else 'Traffic situation'
    keys = {'Pollutant': 'pollutant', 'Process scope': 'process_scope', 'Vehicle category': 'vehicle_class',
            'Ambient cond. pattern': 'ambient_pattern'}
    if situation in raw:
        keys[situation] = 'traffic_situation'
    if 'Gradient' in raw:
        keys['Gradient'] = 'gradient'

    raw = raw.assign(**{'Vehicle category': raw['Vehicle category'].map(hbefa.VEHICLE_CLASSES)})
    if len(raw) != len(stored):
        print(f'  {file.path.name}: {len(raw)} rows in the file, {len(stored)} in the store')
        return False
    # key columns can be empty, which pandas reads as float in one frame and text in the other
    left = raw.assign(**{k: raw[k].astype(object).where(raw[k].notna(), '') for k in keys})
    right = stored.assign(**{k: stored[k].astype(object).where(stored[k].notna(), '') for k in keys.values()})
    merged = left.merge(right, left_on=list(keys), right_on=list(keys.values()))
    if len(merged) != len(stored):
        print(f'  {file.path.name}: only {len(merged)} of {len(stored)} keys match')
        return False
    return all(np.isclose(merged[a], merged[b], **TOLERANCE).all() for a, b in RAW_VALUES.items())


def check_hot_lookup(config, file: hbefa.EfFile) -> bool:
    from hbefa_hot_emissions import HbefaHotEmissions  # v1, flat import by convention

    v1 = HbefaHotEmissions.__new__(HbefaHotEmissions)  # __init__ looks for the old file names
    v1.components = []
    ef = v1._import_hbefa_ef(str(file.path), ['Year', 'Component', 'VehCat', 'TrafficSit', 'Gradient', 'EFA_weighted'],
                             ['Year', 'TrafficSit', 'VehCat', 'Gradient', 'Component'])['EFA_weighted']
    stored = _read(config, file)
    selected = stored[(stored['ambient_pattern'] == V1_HOT_PATTERN) &
                      ~((stored['pollutant'] == 'CO2e') & stored['process_scope'].fillna('').str.startswith('TTW'))]
    ours = {(file.reference_year, r.traffic_situation, r.vehicle_class, r.gradient, r.pollutant): r.efa
            for r in selected.itertuples()}
    return ours == ef


def check_cold_lookup(config, file: hbefa.EfFile) -> bool:
    from hbefa_cold_emissions import HbefaColdEmissions  # v1

    v1 = HbefaColdEmissions.__new__(HbefaColdEmissions)._import_hbefa_coldstart_ef(str(file.path))['EFA_weighted']
    v1 = v1[v1.index.get_level_values('VehCat').notna()]  # v1 has no mapping for MOT in start tables
    stored = _read(config, file)
    ours = stored.set_index(['vehicle_class', 'reference_year', 'pollutant', 'ambient_pattern'])['efa']
    ours = ours.rename_axis(v1.index.names).reindex(v1.index)
    return bool(np.isclose(ours, v1, **TOLERANCE).all())


if __name__ == '__main__':
    config = load_config(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml')
    sys.path.append(str(Path(__file__).resolve().parents[1] / 'utils'))
    results = []
    for file in hbefa.find_files(config.ingest.hbefa.directory, config.ingest.hbefa.version):
        checks = {'file': check_against_file(config, file)}
        if (file.emission_category, file.aggregation) == ('hot', 'single_ts'):
            checks['v1 lookup'] = check_hot_lookup(config, file)
        if file.emission_category == 'start':
            checks['v1 lookup'] = check_cold_lookup(config, file)
        print(f'{file.path.name}: ' + ', '.join(f'{k} {"identical" if v else "DIFFERENT"}' for k, v in checks.items()))
        results += checks.values()
    print('\nEMISSION FACTORS:', 'OK (identical)' if all(results) else 'DIFFERENT')
    sys.exit(0 if all(results) else 1)
