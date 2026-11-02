"""Module to retrieve ambient temperature and align it with the local,
time-zone naive hourly index used by the traffic counts and time profiles.
"""

__version__ = 0.1
__author__ = "Daniel Kühbacher"

import io
import re
import zipfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DWD_HOURLY_TEMPERATURE_URL = ('https://opendata.dwd.de/climate_environment/CDC/'
                              'observations_germany/climate/hourly/air_temperature/')


def _dwd_session() -> requests.Session:
    """Session that retries dropped connections and server errors of opendata.dwd.de."""
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def _read_dwd_zip(period: str, station_id: str) -> pd.DataFrame | None:
    """Downloads one DWD hourly temperature archive ('historical' or 'recent') of a station."""
    session = _dwd_session()
    listing = session.get(DWD_HOURLY_TEMPERATURE_URL + period + '/', timeout=60)
    listing.raise_for_status()
    names = sorted(set(re.findall(rf'stundenwerte_TU_{station_id}_[0-9_]*(?:hist|akt)\.zip',
                                  listing.text)))
    if not names:
        return None

    archive = session.get(DWD_HOURLY_TEMPERATURE_URL + period + '/' + names[-1], timeout=120)
    archive.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        product = next(n for n in z.namelist() if n.startswith('produkt_'))
        return pd.read_csv(z.open(product), sep=';', skipinitialspace=True,
                           usecols=['MESS_DATUM', 'TT_TU'])


def fetch_dwd_temperature(start_date: datetime,
                          end_date: datetime,
                          station_id: str = '03379') -> pd.Series:
    """Downloads hourly 2 m air temperature of a DWD station from opendata.dwd.de.

    Uses the quality-controlled 'historical' archive (until the end of the last
    complete year) and adds the 'recent' archive only if the period reaches beyond it.
    The period is padded by one day on both sides, so that the first and last
    local hours are still covered after conversion from UTC. DWD hourly values are
    in UTC since 2001 (see Metadaten_Parameter in the archive).

    Args:
        start_date (datetime): first day of the period
        end_date (datetime): last day of the period
        station_id (str, optional): DWD station id. Defaults to '03379' (München-Stadt).

    Returns:
        pd.Series: temperature in °C with a UTC tz-aware index, NaN where DWD reports -999
    """
    start = pd.Timestamp(start_date - timedelta(days=1)).tz_localize('UTC')
    end = pd.Timestamp(end_date + timedelta(days=1)).tz_localize('UTC')

    parts = list()
    for period in ['historical', 'recent']:
        df = _read_dwd_zip(period, station_id)
        if df is None:
            continue
        parts.append(df)
        last = pd.to_datetime(str(df['MESS_DATUM'].max()), format='%Y%m%d%H').tz_localize('UTC')
        if last >= end:
            break
    if not parts:
        raise ValueError(f'No DWD hourly temperature data for station {station_id}')

    df = pd.concat(parts)
    index = pd.to_datetime(df['MESS_DATUM'].astype(str), format='%Y%m%d%H').dt.tz_localize('UTC')
    temperature = pd.Series(df['TT_TU'].to_numpy(dtype=float), index=index, name='air_temperature_2m')
    temperature = temperature.replace(-999.0, np.nan)
    # historical (quality controlled) comes first and wins where both archives overlap
    temperature = temperature[~temperature.index.duplicated(keep='first')].sort_index()
    return temperature[start:end]


def to_local_hourly(temperature_utc: pd.Series,
                    index: pd.DatetimeIndex,
                    tz: str = 'Europe/Berlin',
                    max_gap_hours: int = 6) -> pd.Series:
    """Converts a UTC temperature series to hourly local wall-clock time on a naive index.

    Counts and time profiles use local time without time zone and 24 hours per day.
    The repeated hour at the end of daylight saving time is averaged, the skipped
    hour at its start is interpolated.

    Args:
        temperature_utc (pd.Series): temperature with a tz-aware index
        index (pd.DatetimeIndex): naive hourly target index in local time
        tz (str, optional): local time zone. Defaults to 'Europe/Berlin'.
        max_gap_hours (int, optional): longest gap that is interpolated. Defaults to 6.

    Returns:
        pd.Series: hourly temperature on `index`

    Raises:
        ValueError: if the input is not tz-aware or gaps remain after interpolation
    """
    if temperature_utc.index.tz is None:
        raise ValueError('temperature_utc needs a tz-aware index')
    if index.tz is not None:
        raise ValueError('index must be time-zone naive local time')

    hourly = temperature_utc.resample('1h').mean()
    local = hourly.tz_convert(tz).tz_localize(None)
    local = local.groupby(level=0).mean()  # repeated hour at the end of DST

    full_index = local.index.union(index)
    local = local.reindex(full_index).interpolate(limit=max_gap_hours, limit_area='inside')
    result = local.reindex(index)

    missing = result.index[result.isna()]
    if len(missing) > 0:
        raise ValueError(f'{len(missing)} hours without temperature after interpolating gaps '
                         f'up to {max_gap_hours} h, first: {list(missing[:5])}')
    return result.rename(temperature_utc.name)
