"""Compare the hot emission kernel with baseline v1.3-gradientfix, on v1's inputs.

Usage: uv run python scripts/compare_v1_hot.py [configs/munich_2025.yaml]

Isolates the kernel: Activity comes from v1's combined counts file (identical to v1
TrafficCounts, see compare_v1_counts.py), and the links with their share corrections come from
the baseline. Every link and column must match within the tolerance. The kernel's own share
corrections are compared with the baseline's as a separate check.
"""

import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from compare_v1_counts import load_v1  # noqa: E402

from drive import store  # noqa: E402
from drive.config import load_config  # noqa: E402
from drive.domain.activity import Activity  # noqa: E402
from drive.domain.kernel import build_ef_array, hot_emissions, share_corrections  # noqa: E402
from drive.pipeline import kernel_params, load_day_types, load_hot_factors  # noqa: E402

BASELINE = 'inventory/baselines/v1.3-gradientfix/linesource_Munich_2025_hbefa501007_specific_visum2025.gpkg'
YEAR = 2025
RTOL, ATOL = 1e-9, 1e-9


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    config = load_config(config_path)
    params = kernel_params(config)
    root = config.paths.data_root

    baseline = gpd.read_file(root / BASELINE, ignore_geometry=True)
    day_types = load_day_types(config)
    activity = Activity(load_v1(root), day_types, config.run.reference_year, config.run.reference_day_type)
    factors = load_hot_factors(config, YEAR, store.resolve_version(config.paths.store, config.run.data_version))
    dates = pd.date_range(f'{YEAR}-01-01', f'{YEAR}-12-31')

    own = share_corrections(baseline, activity.vehicle_shares, day_types, config.run.reference_year,
                            config.run.reference_day_type)
    corrections_ok = True
    for column in own.columns:
        ok = np.isclose(own[column], baseline[column], rtol=RTOL, atol=ATOL, equal_nan=True)
        corrections_ok &= bool(ok.all())
        print(f'{column}: {(~ok).sum()} of {len(ok)} links differ')

    start = time.perf_counter()
    ef = build_ef_array(baseline, factors, params)
    built = time.perf_counter()
    result = hot_emissions(baseline, baseline[['hgv_corr', 'lcv_corr']], activity, dates, ef, params)
    done = time.perf_counter()
    print(f'Time: factors {built - start:.1f} s, {len(dates)} days on {len(baseline)} links {done - built:.1f} s; '
          f'links with negative volumes: {result.negative_volume_links}')

    new, old = result.emissions.to_numpy(), baseline[result.emissions.columns].to_numpy()
    different = ~np.isclose(new, old, rtol=RTOL, atol=ATOL)
    relative = np.abs(new - old) / np.where(old == 0, np.nan, np.abs(old))
    print(f'Emissions: {different.sum()} of {new.size} values differ, largest relative difference '
          f'{np.nanmax(relative):.2e}')
    for row, column in list(zip(*np.nonzero(different)))[:10]:
        print(f'  link row {row}, {result.emissions.columns[column]}: {new[row, column]} vs {old[row, column]}')

    passed = corrections_ok and not different.any()
    print('OK: kernel matches the baseline' if passed else 'DIFFERENT')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
