"""Compare v2 hot emissions with baseline v1.3-gradientfix.

Usage: uv run python scripts/compare_v1_hot.py [configs/munich_2025.yaml]

1. Kernel on v1's inputs (pass/fail): Activity comes from v1's combined counts file with v1's day types
   (scripts/v1_inputs.py; identical to v1 TrafficCounts, see compare_v1_counts.py), and the links with their
   share corrections come from the baseline. Every link and column must match within the tolerance. The
   kernel's own share corrections (with v1's LCV correction, D25) are compared with the baseline's as a separate check.
   The hourly profile with v1's definition must match v1's hourly worker on sample days.
2. Full chain from the store (reported): totals per component, vehicle class and road type in % of the
   baseline. v2 differs on purpose: VG250 clip area (R23), counts from the raw ingests, store calendar (D22).
   Until those switches the chain matched the baseline row by row within 0.01 % (commit 6cd20b5).
3. Aggregated mode: the kernel on v1's inputs against v1's aggregated line source (pass/fail), and the chain
   from the store (reported). It doesn't use gradients, so the v1.1-asis file is still valid.
"""

import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import v1_inputs
from compare_v1_counts import load_v1

from drive import store
from drive.config import load_config
from drive.domain.activity import Activity
from drive.domain.kernel import (
    build_aggregated_ef_table,
    build_ef_table,
    hot_emissions,
    profile_frame,
    scaling_factors,
    share_corrections,
)
from drive.pipeline import compute_hot_emissions, kernel_params, load_hot_factors

BASELINE = 'inventory/baselines/v1.3-gradientfix/linesource_Munich_2025_hbefa501007_specific_visum2025.gpkg'
YEAR = 2025
RTOL, ATOL = 1e-9, 1e-9
AGGREGATED_BASELINE = 'inventory/baselines/v1.1-asis/linesource_Munich_2025_hbefa501007_aggregated_visum2025.gpkg'
V1_PROFILE = 'inventory/baselines/v1.1-asis/GNFR_F_hot_timeprofile_2025.csv'
# a normal weekday, a Saturday, a Sunday and a day in the summer vacation
PROFILE_DAYS = ['2025-03-04', '2025-03-08', '2025-03-09', '2025-08-13']


def v1_activity(config) -> tuple[Activity, pd.Series]:
    """Activity from v1's combined counts file with v1's day types, and the day types."""
    rows = load_v1(config.paths.data_root)
    years = list(range(rows['date'].dt.year.min(), rows['date'].dt.year.max() + 1))
    day_types = v1_inputs.day_types(config.paths.data_root, years)
    return Activity(rows, day_types, config.run.reference_year, config.run.reference_day_type), day_types


def check_kernel(config, params, baseline: pd.DataFrame) -> bool:
    activity, day_types = v1_activity(config)
    factors = load_hot_factors(config, YEAR, store.resolve_version(config.paths.store, config.run.data_version))
    dates = pd.date_range(f'{YEAR}-01-01', f'{YEAR}-12-31')

    own = share_corrections(baseline, activity.vehicle_shares, day_types, config.run.reference_year,
                            config.run.reference_day_type, classes=('HGV', 'LCV'))  # v1 corrected LCV too (D25)
    corrections_ok = True
    for column in own.columns:
        ok = np.isclose(own[column], baseline[column], rtol=RTOL, atol=ATOL, equal_nan=True)
        corrections_ok &= bool(ok.all())
        print(f'{column}: {(~ok).sum()} of {len(ok)} links differ')

    start = time.perf_counter()
    ef = build_ef_table(baseline, factors, params)
    built = time.perf_counter()
    weights = {'length_km': baseline.length.to_numpy() / 1000, 'v1': np.ones(len(baseline))}
    result = hot_emissions(baseline, baseline[['hgv_corr', 'lcv_corr']], activity, dates, ef, params, weights)
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
    profile_ok = check_profiles(config, params, baseline, activity, result, ef, dates)
    return corrections_ok and not different.any() and profile_ok


def check_profiles(config, params, baseline, activity, result, ef, dates) -> bool:
    """Profiles against the annual totals and v1's hourly worker, and v1's definition against the new one."""
    length = baseline.length.to_numpy() / 1000
    annual = result.emissions.to_numpy() * length[:, None]
    total = result.profiles['length_km'].sum(axis=(0, 1)).ravel()
    closes = np.isclose(total, annual.sum(axis=0), rtol=RTOL)
    print(f'Profile sums to the annual totals: {closes.all()} (largest relative difference '
          f'{np.abs(total / annual.sum(axis=0) - 1).max():.2e})')

    sys.path.append(str(Path(__file__).resolve().parents[1] / 'utils'))
    from hbefa_hot_emissions import HbefaHotEmissions  # v1, flat import by convention
    from hot_emission_process import process_hourly_emissions
    from traffic_counts import TrafficCounts

    v1_rows = baseline[baseline['road_type'] != 'Access-residential'].drop(columns='geometry')
    cycles = TrafficCounts(reference_year=config.run.reference_year)
    hbefa = HbefaHotEmissions(components=params.components, vehicle_classes=params.vehicle_classes,
                              ef_type='EFA_weighted', year=str(YEAR), hbefa_version=config.run.hbefa_version)
    frame = profile_frame(result.profiles['v1'], dates, ef, params)
    frame = frame[frame['road_type'] != 'Access-residential']
    worker_ok = True
    for day in PROFILE_DAYS:
        start = time.perf_counter()
        v1 = pd.DataFrame(process_hourly_emissions(day, v1_rows.to_dict('records'), cycles, hbefa)).sum(axis=1)
        seconds = time.perf_counter() - start
        v1.index.names = ['vehicle_class', 'component', 'hour']
        v2 = frame[frame['time'].dt.strftime('%Y-%m-%d') == day].assign(hour=lambda f: f['time'].dt.hour) \
            .groupby(['vehicle_class', 'component', 'hour'])['emission'].sum()
        v1 = v1.reindex(v2.index)
        close = np.isclose(v2, v1, rtol=RTOL, atol=ATOL)
        worker_ok &= bool(close.all()) and len(v2) == 24 * len(params.vehicle_classes) * len(params.components)
        zero = int((v1 == 0).sum())
        print(f'  {day}: {(~close).sum()} of {len(v2)} values differ from v1\'s hourly worker, {zero} are zero in v1, '
              f'largest relative difference {(np.abs(v2 - v1) / v1.abs().where(v1 != 0)).max():.2e} ({seconds:.0f} s in v1)')

    v1_factors = scaling_factors(frame)
    new_factors = scaling_factors(profile_frame(result.profiles['length_km'], dates, ef, params))
    old_file = pd.read_csv(config.paths.data_root / V1_PROFILE, parse_dates=['timestamp'])
    key = ['component', 'timestamp']
    merged = new_factors.merge(v1_factors, on=key, suffixes=('_new', '_v1')) \
        .merge(old_file[key + ['scaling_factor']].rename(columns={'scaling_factor': 'scaling_factor_file'}), on=key)
    print(f'Hourly scaling factors, {len(merged)} rows:')
    print('  old file vs v1 definition now: largest |difference| '
          f'{(merged["scaling_factor_file"] - merged["scaling_factor_v1"]).abs().max():.4f}, mean '
          f'{(merged["scaling_factor_file"] - merged["scaling_factor_v1"]).abs().mean():.4f}')
    table = []
    for component, group in merged.groupby('component'):
        ratio = group['scaling_factor_new'] / group['scaling_factor_v1']
        month = group.groupby(group['timestamp'].dt.month)[['scaling_factor_new', 'scaling_factor_v1']].mean()
        hour = group.groupby(group['timestamp'].dt.hour)[['scaling_factor_new', 'scaling_factor_v1']].mean()
        table.append({'component': component, 'mean_abs_diff': (group['scaling_factor_new'] - group['scaling_factor_v1']).abs().mean(),
                      'ratio_p1': ratio.quantile(0.01), 'ratio_p99': ratio.quantile(0.99),
                      'monthly_max_%': ((month['scaling_factor_new'] / month['scaling_factor_v1'] - 1) * 100).abs().max(),
                      'hour_of_day_max_%': ((hour['scaling_factor_new'] / hour['scaling_factor_v1'] - 1) * 100).abs().max()})
    print('  new definition vs v1 definition:')
    print(pd.DataFrame(table).round(4).to_string(index=False))
    return bool(closes.all()) and worker_ok


def totals_frame(emissions: pd.DataFrame, road_type: pd.Series, length_km: np.ndarray) -> pd.DataFrame:
    """Annual g per road type, vehicle class and component."""
    grams = emissions.mul(length_km, axis=0).groupby(road_type.to_numpy()).sum().stack()
    frame = grams.rename('g').reset_index()
    frame.columns = ['road_type', 'column', 'g']
    frame[['vehicle_class', 'component']] = frame['column'].str.split('_', n=1, expand=True)
    return frame


def check_chain(config, baseline: gpd.GeoDataFrame) -> None:
    run = compute_hot_emissions(config)
    print(', '.join(f'{stage} {value:.1f} s' for stage, value in run.seconds.items()) +
          f'; store batch {run.version}; links with negative volumes: {run.hot.negative_volume_links}')
    print(f'Link pieces: {len(run.links)} in v2 (VG250), {len(baseline)} in the baseline (v1 boundary)')
    columns = run.hot.emissions.columns
    new = totals_frame(run.hot.emissions, run.links['road_type'], run.links.length.to_numpy() / 1000)
    old = totals_frame(baseline[columns], baseline['road_type'], baseline.length.to_numpy() / 1000)
    frame = new.merge(old, on=['road_type', 'column', 'vehicle_class', 'component'], suffixes=('_new', '_old'))

    def percent(by: list[str]) -> pd.Series:
        totals = frame.groupby(by)[['g_new', 'g_old']].sum()
        return (totals['g_new'] / totals['g_old'] - 1) * 100
    print('All vehicle classes, change in %, by component:')
    print(percent(['component']).round(3).to_string())
    print('By vehicle class:')
    print(percent(['vehicle_class']).round(3).to_string())
    print('By road type:')
    print(percent(['road_type']).round(3).to_string())


def check_aggregated(config, params) -> bool:
    baseline = gpd.read_file(config.paths.data_root / AGGREGATED_BASELINE)
    config = config.model_copy(deep=True)
    config.run.hot_mode = 'aggregated'
    run = config.run
    version = store.resolve_version(config.paths.store, run.data_version)
    activity, _ = v1_activity(config)
    ef = build_aggregated_ef_table(baseline, load_hot_factors(config, YEAR, version), params)
    dates = pd.date_range(f'{YEAR}-01-01', f'{YEAR}-12-31')
    start = time.perf_counter()
    result = hot_emissions(baseline, baseline[['hgv_corr', 'lcv_corr']], activity, dates, ef, params)
    seconds = time.perf_counter() - start
    columns = result.emissions.columns
    new, old = result.emissions.to_numpy(), baseline[columns].to_numpy()
    different = ~np.isclose(new, old, rtol=RTOL, atol=ATOL)
    relative = np.abs(new - old) / np.where(old == 0, np.nan, np.abs(old))
    print(f'On v1 inputs: {different.sum()} of {new.size} values differ, largest relative difference '
          f'{np.nanmax(relative):.2e}; {seconds:.1f} s')

    chain = compute_hot_emissions(config)
    length = chain.links.length.to_numpy() / 1000
    old_length = baseline.length.to_numpy() / 1000
    totals = (chain.hot.emissions.to_numpy() * length[:, None]).sum(axis=0) / (old * old_length[:, None]).sum(axis=0) - 1
    zero = np.isnan(totals)
    print(f'From the store (reported): {len(chain.links)} link pieces against {len(baseline)}; change in totals per '
          f'class x component from {np.nanmin(totals) * 100:.3f} to {np.nanmax(totals) * 100:.3f} %, '
          f'{int(zero.sum())} columns are zero in both')
    profile_total = chain.hot.profiles['length_km'].sum(axis=(0, 1)).ravel()
    annual = (chain.hot.emissions.to_numpy() * length[:, None]).sum(axis=0)
    sums = bool(np.isclose(profile_total, annual, rtol=RTOL, atol=ATOL).all())
    print(f'Profile sums to the annual totals: {sums}')
    return not different.any() and sums


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    config = load_config(config_path)
    params = kernel_params(config)
    baseline = gpd.read_file(config.paths.data_root / BASELINE)

    print('1. Kernel on v1 inputs')
    kernel_ok = check_kernel(config, params, baseline)
    print(f'Kernel: {"OK" if kernel_ok else "DIFFERENT"}\n\n2. Full chain from the store (reported)')
    check_chain(config, baseline)
    print('\n3. Aggregated mode')
    aggregated_ok = check_aggregated(config, params)
    print(f'Aggregated: {"OK" if aggregated_ok else "DIFFERENT"}')
    return 0 if kernel_ok and aggregated_ok else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
