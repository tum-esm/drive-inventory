"""Compare v2 cold start emissions with baseline v1.2-coldfix (2025, visum2025). Reports differences.

Usage: uv run python scripts/compare_v1_cold.py [configs/munich_2025.yaml]

v2 clips to the VG250 area from the store, v1 to its own boundary file, so values per link piece and
totals differ by the clip area (about -0.17 %, spec R23). The port itself was checked exactly against the
baseline with v1's boundary (commit 1577559). Reported, in % of the baseline totals per class and component:
1. On v1's counts and day types (Activity from v1's combined file), v1's start scaling: the clip area only.
2. Full chain from the store, v1's start scaling: plus counts and calendar of v2.
3. Full chain from the store with the configured start scaling (vehicle_specific, spec R40).
The temporal profile of 1. is compared with v1's as well.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import v1_inputs
from compare_v1_counts import load_v1

from drive import store
from drive.config import load_config
from drive.domain.activity import Activity
from drive.domain.kernel import scaling_factors
from drive.pipeline import compute_cold_emissions

BASELINE = Path('inventory/baselines/v1.2-coldfix')


def percent(run, summary: pd.Series) -> pd.Series:
    totals = run.hourly.groupby(['vehicle_class', 'component'])['emission_g'].sum().reindex(summary.index)
    return (totals / summary - 1) * 100


def main(config_path: str) -> int:
    config = load_config(config_path)
    if config.run is None or config.cold_start is None:
        raise ValueError('The config needs the run and cold_start sections')
    root = config.paths.data_root
    summary = pd.read_parquet(root / BASELINE / 'cold_summary_2025.parquet') \
        .set_index(['vehicle_class', 'component'])['total_g']
    scaling = config.cold_start.start_scaling
    config.cold_start.start_scaling = 'v1_share'

    version = store.resolve_version(config.paths.store, config.run.data_version)
    v1_rows = load_v1(root)
    years = list(range(v1_rows['date'].dt.year.min(), v1_rows['date'].dt.year.max() + 1))
    activity = Activity(v1_rows, v1_inputs.day_types(root, years), config.run.reference_year,
                        config.run.reference_day_type)
    on_v1 = compute_cold_emissions(config, activity, version)
    chain = compute_cold_emissions(config)
    config.cold_start.start_scaling = scaling
    configured = compute_cold_emissions(config)

    table = pd.DataFrame({'1. v1 counts': percent(on_v1, summary), '2. store, v1 scaling': percent(chain, summary),
                          f'3. store, {scaling}': percent(configured, summary)})
    print(f'Store batch {version}; change against v1.2-coldfix in %:')
    print(table.round(3).to_string())

    profile = pd.read_csv(root / BASELINE / 'csee_Munich_2025_hbefa501007_visum2025.csv', parse_dates=['timestamp'])
    own = scaling_factors(on_v1.hourly.rename(columns={'emission_g': 'emission'}))
    merged = profile.merge(own, on=['year', 'component', 'timestamp'], suffixes=('_v1', '_v2'))
    diff = (merged['scaling_factor_v1'] - merged['scaling_factor_v2']).abs()
    print(f'Temporal profile of 1. against v1: {len(merged)} of {len(profile)} hours, largest |difference| '
          f'{diff.max():.2g} (the clip area scales the totals, not the shape)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml'))
