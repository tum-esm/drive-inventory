"""Hot emissions of the whole series 2018-2025 with `drive run`'s chain, one output set per year.

Usage: uv run python scripts/run_series.py [configs/munich_2025.yaml] [store|v1_workbook]

Uses v1's choice of traffic model per year until Q14 is decided: 2018-2024 on the 2019 model, 2025
on the 2025 model. Each model has its own counts period, reference year and completeness window,
the settings of v1's two counting files (Q22). Results go to <paths.results>/series_<calendar>.
"""

import sys
from datetime import date
from pathlib import Path

from drive.config import DriveConfig, load_config
from drive.domain.kernel import scaling_factors
from drive.pipeline import compute_hot_emissions, hot_profile, hot_results

YEARS = range(2018, 2026)
SERIES = {'visum2019': {'reference_year': 2019, 'period_start': date(2018, 1, 1)},
          'visum2025': {'reference_year': 2025, 'period_start': date(2019, 1, 1)}}


def series_config(config: DriveConfig, year: int, calendar_source: str) -> DriveConfig:
    """The config of one year of the series."""
    traffic_model = 'visum2025' if year >= 2025 else 'visum2019'
    settings = SERIES[traffic_model]
    reference_year = settings['reference_year']
    config = config.model_copy(deep=True)
    config.run.traffic_model = traffic_model
    config.run.reference_year = reference_year
    config.run.start, config.run.end = date(year, 1, 1), date(year, 12, 31)
    config.run.calendar_source = calendar_source
    config.counts_qa.period_start = settings['period_start']
    config.counts_qa.completeness_window = (date(reference_year, 1, 1), date(reference_year, 12, 31))
    config.paths.results = config.paths.results / f'series_{calendar_source}'
    return config


def main(config_path: str = 'configs/munich_2025.yaml', calendar_source: str = 'store') -> int:
    base = load_config(config_path)
    for year in YEARS:
        config = series_config(base, year, calendar_source)
        run = compute_hot_emissions(config)
        profile = hot_profile(run, config)
        results = config.paths.results
        results.mkdir(parents=True, exist_ok=True)
        stem = f'{config.run.traffic_model}_{year}_hbefa{config.run.hbefa_version}_batch{run.version}'
        hot_results(run).to_parquet(results / f'hot_{stem}.parquet')
        profile.to_parquet(results / f'hot_profile_{stem}.parquet')
        scaling_factors(profile.rename(columns={'emission_g': 'emission'})) \
            .to_csv(results / f'hot_timeprofile_{stem}.csv', index=False)
        timing = ', '.join(f'{stage} {value:.1f} s' for stage, value in run.seconds.items())
        print(f'{year} {config.run.traffic_model}: {len(run.links)} rows, batch {run.version}, '
              f'negative volume links {run.hot.negative_volume_links}; {timing}', flush=True)
    print(f'Results in {Path(results)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
