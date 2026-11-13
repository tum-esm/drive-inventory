"""DWD hourly 2 m air temperature from opendata.dwd.de (port of v1 utils/meteo.py, download part).

Returns the raw station values in UTC (DWD hourly data is in UTC since 2001, see Metadaten_Parameter
in the archive). Combining stations and converting to local time are compute steps, see domain.meteo.
"""

import io
import re
import zipfile

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from drive.schemas import TEMPERATURES

URL = 'https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/'
# 'historical' is quality controlled and ends with the last complete year; 'recent' covers about the last 500 days
ARCHIVES = ['historical', 'recent']


def _session() -> requests.Session:
    """Session that retries dropped connections and server errors of opendata.dwd.de."""
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def _read_archive(session: requests.Session, archive: str, station_id: str) -> tuple[pd.DataFrame, str] | None:
    """Rows of one archive of a station and the URL they came from, None if the station has none."""
    listing = session.get(URL + archive + '/', timeout=60)
    listing.raise_for_status()
    names = sorted(set(re.findall(rf'stundenwerte_TU_{station_id}_[0-9_]*(?:hist|akt)\.zip', listing.text)))
    if not names:
        return None
    url = URL + archive + '/' + names[-1]
    response = session.get(url, timeout=120)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        product = next(n for n in z.namelist() if n.startswith('produkt_'))
        df = pd.read_csv(z.open(product), sep=';', skipinitialspace=True, usecols=['MESS_DATUM', 'QN_9', 'TT_TU'])
    return df, url


def fetch_temperatures(station_id: str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, list[str]]:
    """Hourly temperatures of one station in [start, end) UTC (contract drive.schemas.TEMPERATURES).

    Where both archives have an hour, the quality-controlled 'historical' value wins.
    DWD's missing-value marker -999 becomes NaN; the hour stays, so a gap is visible in the store.

    Returns:
        the rows and the archive URLs they came from

    Raises:
        ValueError: if the station has no archive
    """
    session = _session()
    parts, urls = [], []
    for archive in ARCHIVES:
        read = _read_archive(session, archive, station_id)
        if read is None:
            continue
        df, url = read
        parts.append(df.assign(archive=archive))
        urls.append(url)
    if not parts:
        raise ValueError(f'No DWD hourly temperature archive for station {station_id}')

    df = pd.concat(parts, ignore_index=True)
    df['timestamp_utc'] = pd.to_datetime(df['MESS_DATUM'].astype(str), format='%Y%m%d%H')
    df = df[(df['timestamp_utc'] >= start) & (df['timestamp_utc'] < end)]
    df = df.drop_duplicates('timestamp_utc', keep='first')  # parts are in ARCHIVES order
    rows = pd.DataFrame({
        'station_id': station_id,
        'timestamp_utc': df['timestamp_utc'].astype('datetime64[us]'),
        'air_temperature': df['TT_TU'].astype(float).replace(-999.0, np.nan),
        'quality_level': df['QN_9'].astype('int64'),
        'archive': df['archive'],
    }).sort_values('timestamp_utc', ignore_index=True)
    return TEMPERATURES.validate(rows), urls
