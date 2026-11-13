"""Compare v2 cold start emissions with baseline v1.2-coldfix (2025, visum2025).

Usage: uv run python scripts/compare_v1_cold.py [configs/munich_2025.yaml]

Both checks use v1's day types (run.calendar_source = v1_workbook).
1. On v1's counts: Activity from v1's combined counts file, everything else from the store
   (links, zones, temperatures, start factors). Totals per vehicle class and component, every
   link piece (g/km) and the temporal profile must match the baseline within the tolerance.
2. Full chain from the store: differences come only from the known count differences
   (BASt -1 markers, compare_v1_counts.py), reported as relative differences of the totals.
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from compare_v1_counts import load_v1

from drive import store
from drive.config import load_config
from drive.domain.activity import Activity
from drive.domain.kernel import scaling_factors
from drive.pipeline import cold_results, compute_cold_emissions, load_day_types

BASELINE = Path('inventory/baselines/v1.2-coldfix')
RTOL = 1e-9
CHAIN_LIMIT_PERCENT = 0.01


def totals(run) -> pd.Series:
    return run.hourly.groupby(['vehicle_class', 'component'])['emission_g'].sum()


def check_on_v1_inputs(config) -> bool:
    root = config.paths.data_root
    version = store.resolve_version(config.paths.store, config.run.data_version)
    activity = Activity(load_v1(root), load_day_types(config, version), config.run.reference_year,
                        config.run.reference_day_type)
    run = compute_cold_emissions(config, activity, version)
    ok = True

    summary = pd.read_parquet(root / BASELINE / 'cold_summary_2025.parquet') \
        .set_index(['vehicle_class', 'component'])['total_g']
    v2 = totals(run).reindex(summary.index)
    rel = ((v2 - summary) / summary).abs()
    ok &= bool((rel <= RTOL).all())
    print(f'1. totals: max rel. diff {rel.max():.2g} over {len(rel)} class x component')

    baseline = gpd.read_file(root / BASELINE / 'csee_Munich_2025_hbefa501007_visum2025.gpkg')
    results = cold_results(run)
    if len(baseline) != len(results):
        print(f'   links: {len(baseline)} pieces in v1, {len(results)} in v2')
        return False
    columns = [c for c in baseline.columns if c != 'geometry']
    a, b = baseline[columns].to_numpy(), results[columns].to_numpy()
    close = np.isclose(a, b, rtol=RTOL, atol=1e-12)
    ok &= bool(close.all())
    print(f'   links: {len(results)} pieces x {len(columns)} columns, {(~close).sum()} outside the tolerance, '
          f'max rel. diff {np.nanmax(np.abs(a - b) / np.maximum(np.abs(a), 1e-300)):.2g}')

    profile = pd.read_csv(root / BASELINE / 'csee_Munich_2025_hbefa501007_visum2025.csv', parse_dates=['timestamp'])
    own = scaling_factors(run.hourly.rename(columns={'emission_g': 'emission'}))
    merged = profile.merge(own, on=['year', 'component', 'timestamp'], how='outer', suffixes=('_v1', '_v2'))
    diff = (merged['scaling_factor_v1'] - merged['scaling_factor_v2']).abs()
    ok &= bool(len(merged) == len(profile) == len(own) and (diff <= RTOL).all())
    print(f'   profile: {len(own)} rows (v1 {len(profile)}), max abs. diff {diff.max():.2g}')
    print(f'   daily starts within the boundary {run.daily_starts}; temperature hours from the backup '
          f'{run.temperature.from_backup}')
    return ok


def check_chain(config) -> bool:
    run = compute_cold_emissions(config)
    summary = pd.read_parquet(config.paths.data_root / BASELINE / 'cold_summary_2025.parquet') \
        .set_index(['vehicle_class', 'component'])['total_g']
    rel = (totals(run).reindex(summary.index) - summary) / summary * 100
    print(f'2. chain from the store: max |rel. diff| {rel.abs().max():.4f} % (limit {CHAIN_LIMIT_PERCENT} %)')
    print(rel.round(5).unstack('component').to_string())
    return bool(rel.abs().max() <= CHAIN_LIMIT_PERCENT)


def main(config_path: str) -> int:
    config = load_config(config_path)
    if config.run is None:
        raise ValueError('The config needs the run section')
    config.run.calendar_source = 'v1_workbook'  # v1's day types and profile groups
    if config.cold_start is None:
        raise ValueError('The config needs the cold_start section')
    config.cold_start.start_scaling = 'v1_share'  # v1's start profile (spec R40)
    ok = check_on_v1_inputs(config)
    ok &= check_chain(config)
    print('OK' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml'))
