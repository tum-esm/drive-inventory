"""Compare the v2 counts QA and Activity with v1.

Usage: uv run python scripts/compare_v1_counts.py [configs/munich_2025.yaml]

Pass/fail: Activity is built from v1's combined file with v1's day types (scripts/v1_inputs.py) and
compared with v1 TrafficCounts on the same input. It must be identical.

Reported, not checked: the counts QA (data_preprocessing/31 -> counting_data_combined.parquet) and the full
chain (store -> QA -> Activity) against v1 for both periods. v2 now differs from v1 on purpose: counts from
the raw exports and archives (BASt 2021-2022 raw instead of annual, flags), the store calendar (D22), R3
(links without data in the completeness window are incomplete), the class-share check (R44) and the
completeness per year (R46: valid and >= 80 % in the reference year and the year, only those rows go into Activity). Until the switch to the raw ingests, the only
differences were R3 and BASt's -1 markers (commit cc324e9).
"""

import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt

from drive import store
from drive.config import load_config
from drive.domain.activity import Activity
from drive.pipeline import load_activity, load_day_types, load_link_counts
from drive.schemas import HOURS

sys.path.insert(0, str(Path(__file__).parent))
import v1_inputs

V1_FILE = 'restricted_input/counting_data/counting_data_combined.parquet'
V1_FILE_FROM_2018 = 'restricted_input/counting_data/counting_data_combined_from2018.parquet'
KEY = ['road_link_id', 'vehicle_class', 'date']
FLOAT_TOLERANCE = 1e-9
V1_COMPLETENESS_THRESHOLD = 0.6  # v1: share of the best covered link's days in the window


def load_v1(data_root: Path, file: str = V1_FILE) -> pd.DataFrame:
    v1 = pd.read_parquet(data_root / file)
    v1 = v1.rename(columns={str(h): f'h{h:02d}' for h in range(24)} | {'completness': 'completeness'})
    v1['road_link_id'] = v1['road_link_id'].astype('int64')
    v1['date'] = v1['date'].astype('datetime64[us]')
    return v1


def marker_link_classes(config) -> pd.DataFrame:
    """(road_link_id, vehicle_class) pairs with missing BASt hours in 2019-2025 (v1's -1 markers, flags since)."""
    raw = store.read_counts(config.paths.store, config.run.data_version, metric='volume',
                            start=config.counts_qa.period_start.isoformat())
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
    differs |= both & (merged['complete_v1'] != merged['complete_v2'])  # v2: per year (R46)

    markers = marker_link_classes(config).assign(_marker=True)
    diff = merged[differs].merge(markers, on=['road_link_id', 'vehicle_class'], how='left')
    explained = diff['_marker'].fillna(False).astype(bool)

    print(f'\nRows that differ: {len(diff)} (only v1: {(diff["_merge"] == "left_only").sum()}, '
          f'only v2: {(diff["_merge"] == "right_only").sum()}, values: {(diff["_merge"] == "both").sum()})')
    print(f'  on links with missing BASt hours: {explained.sum()} rows on '
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


def _report(name: str, v2: pd.Series | pd.DataFrame, v1: pd.Series | pd.DataFrame) -> bool:
    """Compares v2 with v1 at float tolerance; index and column order are ignored."""
    try:
        compare = pdt.assert_frame_equal if isinstance(v2, pd.DataFrame) else pdt.assert_series_equal
        compare(v2, v1, rtol=FLOAT_TOLERANCE, atol=FLOAT_TOLERANCE, check_like=True, check_names=False,
                check_index_type=False, check_dtype=False, check_freq=False)
    except AssertionError as error:
        print(f'  {name}: DIFFERENT\n{error}')
        return False
    print(f'  {name}: identical ({len(v2)} rows, {int(v2.isna().sum().sum())} NaN)')
    return True


def compare_activity(config) -> bool:
    """Pure-port check: Activity and v1 TrafficCounts on the same input, v1's combined file."""
    sys.path.append(str(Path(__file__).resolve().parents[1] / 'utils'))
    from traffic_counts import TrafficCounts  # v1, flat import by convention

    v1_input = load_v1(config.paths.data_root)
    years = list(range(v1_input['date'].dt.year.min(), v1_input['date'].dt.year.max() + 1))
    day_types = v1_inputs.day_types(config.paths.data_root, years)

    start = time.perf_counter()
    v2 = Activity(v1_input, day_types, config.run.reference_year, config.run.reference_day_type)
    v2_seconds = time.perf_counter() - start
    start = time.perf_counter()
    v1 = TrafficCounts(reference_year=config.run.reference_year, reference_day_type=config.run.reference_day_type)
    print(f'Built Activity in {v2_seconds:.1f} s, TrafficCounts in {time.perf_counter() - start:.1f} s')

    v1_cycles = v1.daily_cycles.rename(columns={str(h): f'h{h:02d}' for h in range(24)})
    results = [_report('vehicle_shares', v2.vehicle_shares, v1.vehicle_shares),
               _report('annual_cycles', v2.annual_cycles, v1.annual_cycles),
               _report('daily_cycles', v2.daily_cycles.sort_index(), v1_cycles.sort_index())]
    results.append(set(v2.road_types) == set(v1.road_types))
    for road_type in v2.road_types:
        v1_profile = v1.timeprofile[road_type].rename_axis('time')
        results.append(_report(f'timeprofile {road_type}', v2.timeprofile[road_type], v1_profile))
        zero_v1 = v1_profile.resample('D').sum(min_count=1).eq(0).all(axis=1)
        missing = v2.missing_days[road_type]
        print(f'    missing_days: {len(missing)}, all-zero days in v1: {zero_v1.sum()}, '
              f'same days: {set(missing) == set(zero_v1[zero_v1].index)}')
    return all(results)


def _print_effect(name: str, new: Activity, old: Activity) -> None:
    """Size of the differences between two activities, per scaling road type."""
    print(f'  {name}:')
    for road_type in new.road_types:
        annual = (new.annual_cycles.xs(road_type, level='scaling_road_type') /
                  old.annual_cycles.xs(road_type, level='scaling_road_type') - 1).abs()
        shares = (new.vehicle_shares.xs(road_type, level='scaling_road_type') -
                  old.vehicle_shares.xs(road_type, level='scaling_road_type')).abs()
        last_year = str(new.date_end.year)
        total_new = new.timeprofile[road_type].loc[last_year].sum()
        total_old = old.timeprofile[road_type].loc[last_year].sum()
        profile = ((total_new / total_old - 1) * 100).round(4).to_dict()
        print(f'    {road_type}: annual cycle days changed {int((annual > FLOAT_TOLERANCE).sum())}, '
              f'max {annual.max():.2%}; shares max {shares.max():.4f}; '
              f'{last_year} profile totals in %: {profile}')


def compare_chain(config, start: date, v1_file: str, traffic_model: str, reference_year: int) -> bool:
    """v2 from the store against v1, split into R3 and the BASt markers.

    Activity on v1's file stands in for TrafficCounts (compare_activity shows they are identical).
    The settings must be those the v1 file was built with.
    """
    config = config.model_copy(deep=True)
    config.counts_qa.period_start = start
    config.run.traffic_model = traffic_model
    config.run.reference_year = reference_year
    run = config.run
    print(f'\nFull chain from {start}, {traffic_model}, reference year {reference_year}, '
          f'v1 file {Path(v1_file).name}:')

    v2, report, version = load_activity(config)
    print(f'  store batch {version}; links {report.links}, valid {report.links_valid}, '
          f'complete in the reference year {report.links_complete_reference}; missing days { {k: len(v) for k, v in v2.missing_days.items()} }; '
          f'NaN hours { {k: int(v.isna().any(axis=1).sum()) for k, v in v2.timeprofile.items()} }')

    day_types = load_day_types(config)
    v1_rows = load_v1(config.paths.data_root, v1_file)
    v1_r3_rows = v1_rows.assign(complete=v1_rows['completeness'] > V1_COMPLETENESS_THRESHOLD)
    v1 = Activity(v1_rows, day_types, run.reference_year, run.reference_day_type)
    v1_r3 = Activity(v1_r3_rows, day_types, run.reference_year, run.reference_day_type)
    _print_effect('R3 (v1 with the R3 rule vs v1)', v1_r3, v1)
    _print_effect('v2 chain vs v1 with the R3 rule', v2, v1_r3)

    # Without the marker links nothing else may differ
    marker_links = set(marker_link_classes(config)['road_link_id'])
    v2_rows, _, _ = load_link_counts(config)
    print(f'  without the {len(marker_links)} links with missing BASt hours, v2 chain vs v1 with the R3 rule:')
    clean_v2 = Activity(v2_rows[~v2_rows['road_link_id'].isin(marker_links)], day_types,
                        run.reference_year, run.reference_day_type)
    clean_v1 = Activity(v1_r3_rows[~v1_r3_rows['road_link_id'].isin(marker_links)], day_types,
                        run.reference_year, run.reference_day_type)
    results = [_report('vehicle_shares', clean_v2.vehicle_shares, clean_v1.vehicle_shares),
               _report('annual_cycles', clean_v2.annual_cycles, clean_v1.annual_cycles),
               _report('daily_cycles', clean_v2.daily_cycles, clean_v1.daily_cycles)]
    results += [_report(f'timeprofile {rt}', clean_v2.timeprofile[rt], clean_v1.timeprofile[rt])
                for rt in clean_v2.road_types]
    return all(results)


def report_period_effect(config) -> None:
    """Outliers are detected over all years, so the start of the period changes every year's activity."""
    activities = {}
    for start in [date(2018, 1, 1), date(2019, 1, 1)]:
        period = config.model_copy(deep=True)
        period.counts_qa.period_start = start
        activities[start.year], _, _ = load_activity(period)
    print('\nPeriod effect, production settings, period from 2018 vs from 2019, all classes per year in %:')
    for road_type in activities[2018].road_types:
        totals = {year: a.timeprofile[road_type].loc['2019':].resample('YE').sum().sum(axis=1)
                  for year, a in activities.items()}
        change = (totals[2018] / totals[2019] - 1) * 100
        print(f'  {road_type}: ' + ', '.join(f'{t.year}: {v:+.3f}' for t, v in change.items()))


if __name__ == '__main__':
    config = load_config(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml')
    print('Activity on v1 input vs TrafficCounts:')
    activity_ok = compare_activity(config)
    print('\nACTIVITY:', 'OK (identical)' if activity_ok else 'DIFFERENT')
    print('\nReported only, v2 differs from v1 on purpose (see the docstring):')
    compare_link_counts(config)
    compare_chain(config, date(2019, 1, 1), V1_FILE, 'visum2025', 2025)
    compare_chain(config, date(2018, 1, 1), V1_FILE_FROM_2018, 'visum2019', 2019)
    report_period_effect(config)
    sys.exit(0 if activity_ok else 1)
