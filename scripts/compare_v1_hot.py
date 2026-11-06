"""Compare v2 hot emissions with baseline v1.3-gradientfix.

Usage: uv run python scripts/compare_v1_hot.py [configs/munich_2025.yaml]

1. Kernel on v1's inputs: Activity comes from v1's combined counts file (identical to v1
   TrafficCounts, see compare_v1_counts.py), and the links with their share corrections come
   from the baseline. Every link and column must match within the tolerance. The kernel's own
   share corrections are compared with the baseline's as a separate check.
2. Full chain from the store: clipped links must match the baseline row by row. Emissions may
   differ only through the known count differences (BASt -1 markers, compare_v1_counts.py), so
   the differences are reported per road type, vehicle class and component.
"""

import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from compare_v1_counts import load_v1, marker_link_classes  # noqa: E402

from drive import store  # noqa: E402
from drive.config import load_config  # noqa: E402
from drive.domain.activity import Activity  # noqa: E402
from drive.domain.kernel import build_ef_array, hot_emissions, share_corrections  # noqa: E402
from drive.pipeline import (compute_hot_emissions, kernel_params, load_day_types, load_hot_factors,  # noqa: E402
                            load_link_counts)

BASELINE = 'inventory/baselines/v1.3-gradientfix/linesource_Munich_2025_hbefa501007_specific_visum2025.gpkg'
YEAR = 2025
RTOL, ATOL = 1e-9, 1e-9
CHAIN_LIMIT_PERCENT = 0.01  # per road type x vehicle class x component


def check_kernel(config, params, baseline: pd.DataFrame) -> bool:
    root = config.paths.data_root
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
    return corrections_ok and not different.any()


def check_chain(config, baseline: gpd.GeoDataFrame) -> bool:
    run = compute_hot_emissions(config)
    links = run.links
    print(', '.join(f'{stage} {value:.1f} s' for stage, value in run.seconds.items()) +
          f'; store batch {run.version}; links with negative volumes: {run.hot.negative_volume_links}')

    ok = len(links) == len(baseline)
    print(f'Rows: {len(links)} in v2, {len(baseline)} in the baseline')
    if not ok:
        return False
    for column in ['road_link_id', 'road_type', 'scaling_road_type', 'hour_capacity', 'lanes', 'hbefa_speed', 'speed',
                   'hbefa_gradient', 'dtv_SUM', 'dtv_HGV', 'dtv_PC', 'dtv_LCV']:
        different = links[column].to_numpy() != baseline[column].to_numpy()
        ok &= not different.any()
        if different.any():
            print(f'  {column} differs in {different.sum()} rows')
    same_geometry = links.geometry.reset_index(drop=True).geom_equals_exact(baseline.geometry, 0)
    ok &= bool(same_geometry.all())
    print(f'Link attributes match: {ok}; rows with different geometry: {(~same_geometry).sum()}')

    columns = run.hot.emissions.columns
    for name in ['hgv_corr', 'lcv_corr']:
        old_corrections = baseline[name].to_numpy()
        relative = np.abs(run.corrections[name].to_numpy() - old_corrections) / np.where(old_corrections == 0, 1, old_corrections)
        print(f'{name}: largest relative difference {relative.max():.2e}')

    length = links.length.to_numpy() / 1000
    new, old = run.hot.emissions.to_numpy(), baseline[columns].to_numpy()
    per_link = np.abs(new - old) / np.where(old == 0, np.nan, np.abs(old))
    print(f'Per link: {(~np.isclose(new, old, rtol=RTOL, atol=ATOL)).sum()} of {new.size} values differ, '
          f'median relative difference {np.nanmedian(per_link):.2e}, largest {np.nanmax(per_link):.2e}')

    frame = pd.DataFrame({'road_type': np.repeat(links['road_type'].to_numpy(), len(columns)),
                          'column': np.tile(columns, len(links)),
                          'new': (new * length[:, None]).ravel(), 'old': (old * length[:, None]).ravel()})
    frame[['vehicle_class', 'component']] = frame['column'].str.split('_', n=1, expand=True)
    def percent(by: list[str]) -> pd.Series:
        totals = frame.groupby(by)[['new', 'old']].sum()
        return (totals['new'] / totals['old'] - 1) * 100
    print('All vehicle classes, change in %, by component:')
    print(percent(['component']).round(5).to_string())
    print('By vehicle class:')
    print(percent(['vehicle_class']).round(5).to_string())
    print('By road type:')
    print(percent(['road_type']).round(5).to_string())
    detail = percent(['road_type', 'vehicle_class', 'component'])
    print(f'Largest change per road type x class x component: {detail.abs().max():.5f} % at {detail.abs().idxmax()}')
    print(f'Within {CHAIN_LIMIT_PERCENT} %: {bool(detail.abs().max() <= CHAIN_LIMIT_PERCENT)}')
    return ok and bool(detail.abs().max() <= CHAIN_LIMIT_PERCENT)


def check_markers(config, params, baseline: pd.DataFrame) -> bool:
    """Without the links with BASt markers, the chain and v1's counts must give the same emissions."""
    day_types = load_day_types(config)
    run = config.run
    markers = set(marker_link_classes(config)['road_link_id'])
    v2_rows = load_link_counts(config)[0]
    v1_rows = load_v1(config.paths.data_root)
    # with the R3 rule, as in compare_v1_counts.py, so that only the markers can differ
    v1_rows = v1_rows.assign(complete=v1_rows['completeness'] > config.counts_qa.completeness_threshold)
    def emissions(rows: pd.DataFrame) -> np.ndarray:
        activity = Activity(rows[~rows['road_link_id'].isin(markers)], day_types, run.reference_year, run.reference_day_type)
        corrections = share_corrections(baseline, activity.vehicle_shares, day_types, run.reference_year, run.reference_day_type)
        factors = load_hot_factors(config, YEAR, store.resolve_version(config.paths.store, run.data_version))
        dates = pd.date_range(f'{YEAR}-01-01', f'{YEAR}-12-31')
        return hot_emissions(baseline, corrections, activity, dates, build_ef_array(baseline, factors, params), params) \
            .emissions.to_numpy()
    new, old = emissions(v2_rows), emissions(v1_rows)
    different = ~np.isclose(new, old, rtol=RTOL, atol=ATOL)
    print(f'Without {len(markers)} marker links: {different.sum()} of {new.size} values differ')
    return not different.any()


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    config = load_config(config_path)
    params = kernel_params(config)
    baseline = gpd.read_file(config.paths.data_root / BASELINE)

    print('1. Kernel on v1 inputs')
    kernel_ok = check_kernel(config, params, baseline)
    print(f'Kernel: {"OK" if kernel_ok else "DIFFERENT"}\n\n2. Full chain from the store')
    chain_ok = check_chain(config, baseline)
    print(f'Chain: {"OK" if chain_ok else "DIFFERENT"}\n\n3. Are the BASt markers the only cause?')
    markers_ok = check_markers(config, params, baseline)
    print(f'Markers: {"OK" if markers_ok else "DIFFERENT"}')
    return 0 if kernel_ok and chain_ok and markers_ok else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
