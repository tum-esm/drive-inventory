"""Hot and cold start emissions of the whole series 2018-2025 with `drive run`'s chain, one output set per year.

Usage: uv run python scripts/run_series.py [configs/munich_2025.yaml]

Traffic model per year (spec Q14, D31): the 2019 model for 2018-2025, the 2025 model from 2025 on. 2025 is
computed with both, so the 2019 model's estimate for 2025 can be compared with the 2025 model's. Each model has its
own counts period and reference year, the settings of v1's two counting files (Q22). Results go to
<paths.results>/series; the file names carry the model.
"""

import sys
from datetime import date
from pathlib import Path

from drive.config import DriveConfig, load_config
from drive.pipeline import run_inventory

# (year, traffic model) of every run (D31)
RUNS = [(year, 'visum2019') for year in range(2018, 2026)] + [(2025, 'visum2025')]
SERIES = {'visum2019': {'reference_year': 2019, 'period_start': date(2018, 1, 1)},
          'visum2025': {'reference_year': 2025, 'period_start': date(2019, 1, 1)}}


def series_config(config: DriveConfig, year: int, traffic_model: str | None = None) -> DriveConfig:
    """The config of one run of the series; without a model, the newest one for the year (D31)."""
    traffic_model = traffic_model or ('visum2025' if year >= 2025 else 'visum2019')
    settings = SERIES[traffic_model]
    reference_year = settings['reference_year']
    config = config.model_copy(deep=True)
    config.run.traffic_model = traffic_model
    config.run.reference_year = reference_year
    config.run.start, config.run.end = date(year, 1, 1), date(year, 12, 31)
    config.counts_qa.period_start = settings['period_start']
    config.paths.results = config.paths.results / 'series'
    return config


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    base = load_config(config_path)
    for year, traffic_model in RUNS:
        config = series_config(base, year, traffic_model)
        print(f'{year} {config.run.traffic_model}:', flush=True)
        for line in run_inventory(config):
            print(f'    {line}', flush=True)
    print(f'Results in {Path(config.paths.results)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
