"""Check the temperatures of `drive run` against v1's route (utils/meteo.py and notebook 11).

Usage: uv run python scripts/compare_v1_meteo.py [configs/munich_2025.yaml]

For each year 2018-2025: v1 downloads both stations from DWD, fills the main station's gaps from
the backup and converts to local time; v2 reads the store (`drive ingest meteo`) and does the same
in domain.meteo. The two hourly series must be identical. Also prints the hours taken from the
backup station (the v1.2-coldfix baseline notes 72 for 2025) and the interpolated hours.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from drive.config import load_config
from drive.pipeline import load_temperature

sys.path.append(str(Path(__file__).resolve().parents[1] / 'utils'))
import meteo  # v1 module


def v1_temperature(year: int, station: str, backup: str, max_gap_hours: int) -> tuple[pd.Series, int]:
    start, end = datetime(year, 1, 1, 0, 0), datetime(year, 12, 31, 23, 59)
    main = meteo.fetch_dwd_temperature(start, end, station_id=station)
    other = meteo.fetch_dwd_temperature(start, end, station_id=backup)
    filled = other.index[other.notna() & main.reindex(other.index).isna()]
    index = pd.date_range(start=start, end=end, freq='1h')
    return meteo.to_local_hourly(main.combine_first(other), index=index, max_gap_hours=max_gap_hours), len(filled)


def main(config_path: str) -> int:
    config = load_config(config_path)
    t = config.run.temperature if config.run else None
    if t is None or t.backup_station is None:
        raise ValueError('The config needs run.temperature with a backup station')
    failed = False
    for year in range(2018, 2026):
        index = pd.date_range(datetime(year, 1, 1), datetime(year, 12, 31, 23), freq='1h')
        v2, report = load_temperature(config, index)
        v1, v1_backup = v1_temperature(year, t.station, t.backup_station, t.max_gap_hours)
        diff = (v2 - v1).abs()
        ok = v2.index.equals(v1.index) and diff.max() == 0 and report.from_backup == v1_backup
        failed |= not ok
        print(f'{year}: {"identical" if ok else "DIFFERENT"}, {len(v2)} h, max |diff| {diff.max():.3g} °C, '
              f'from backup v2 {report.from_backup} / v1 {v1_backup} UTC hours, interpolated {report.interpolated} h, '
              f'mean {v2.mean():.2f} °C')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml'))
