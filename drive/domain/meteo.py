"""Hourly ambient temperature on the local, time-zone naive hourly index of counts and profiles.

Port of v1 notebook 11 (station combination) and utils/meteo.to_local_hourly. No IO.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class TemperatureReport:
    from_backup: int  # UTC hours missing at the main station and taken from the backup station
    interpolated: int  # local hours filled by interpolation


def station_series(rows: pd.DataFrame) -> pd.Series:
    """Temperature of one station (TEMPERATURES rows) as a series with a tz-aware UTC index, NaN kept."""
    index = pd.DatetimeIndex(rows['timestamp_utc']).tz_localize('UTC')
    return pd.Series(rows['air_temperature'].to_numpy(dtype=float), index=index, name='air_temperature')


def combine_stations(main: pd.Series, backup: pd.Series | None) -> tuple[pd.Series, int]:
    """Main station, with its missing hours taken from the backup station.

    Returns:
        the combined series and the number of hours taken from the backup
    """
    if backup is None:
        return main, 0
    filled = backup.index[backup.notna() & main.reindex(backup.index).isna()]
    return main.combine_first(backup), len(filled)


def to_local_hourly(temperature_utc: pd.Series,
                    index: pd.DatetimeIndex,
                    tz: str,
                    max_gap_hours: int) -> tuple[pd.Series, int]:
    """Converts a UTC temperature series to hourly local wall-clock time on a naive index.

    Counts and time profiles use local time without time zone and 24 hours per day.
    The repeated hour at the end of daylight saving time is averaged, the skipped
    hour at its start is interpolated.

    Returns:
        hourly temperature on `index`, and the number of its hours filled by interpolation

    Raises:
        ValueError: if the input is not tz-aware or gaps remain after interpolation
    """
    if not isinstance(temperature_utc.index, pd.DatetimeIndex) or temperature_utc.index.tz is None:
        raise ValueError('temperature_utc needs a tz-aware index')
    if index.tz is not None:
        raise ValueError('index must be time-zone naive local time')

    hourly = temperature_utc.resample('1h').mean()
    local = hourly.tz_convert(tz).tz_localize(None)
    local = local.groupby(level=0).mean()  # repeated hour at the end of DST

    full_index = local.index.union(index)
    before = local.reindex(index)
    local = local.reindex(full_index).interpolate(limit=max_gap_hours, limit_area='inside')
    result = local.reindex(index)

    missing = result.index[result.isna()]
    if len(missing) > 0:
        raise ValueError(f'{len(missing)} hours without temperature after interpolating gaps '
                         f'up to {max_gap_hours} h, first: {list(missing[:5])}')
    result.name = temperature_utc.name
    return result, int(before.isna().sum())
