"""BASt automatic permanent counting stations (Dauerzählstellen) on federal roads: hourly counts and locations.

Port of v1 data_preprocessing/11 and counting_data/bast/download_bast_data*.ipynb. Format reference: BASt,
"BASt-Bestandsbandformat für Verkehrsmengendaten, Version 2004" (DZ-Beschreibung.pdf on the download page).

The station table (annual files zst<station>_<year>.csv, one row per station and hour, both directions as
columns `<class>_R1/_R2` with a flag `K_<class>_R1/_R2`) is read into one detector per direction:
detector_id = station + '1' or '2' (v1).
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from drive.io.counter_links import links_per_model
from drive.schemas import HOURS, RAW_COUNTS

SOURCE = 'BASt'

# v1 classes from the BASt columns. Lzg are trucks with trailer including articulated trucks (LmA + Sat), so Sat
# is not added again; PLZ (Mot + Pkw + Lfw of 5+1 stations) and Son (not classifiable) are not used, as in v1.
CLASSES = {'SUM': ['KFZ'], 'PC': ['Pkw', 'PmA'], 'LCV': ['Lfw'], 'HGV': ['LoA', 'Lzg'], 'BUS': ['Bus'], 'MOT': ['Mot']}

# flags from best to worst; a class made of several columns gets the worst flag of its parts. 'x' is not in the
# 2004 description: it always comes with -1 and marks a class the station does not count (v1's -1 markers).
FLAG_ORDER = '-zuksdax'


@dataclass
class BastReport:
    stations: int = 0
    station_days: int = 0
    first_date: str = ''
    last_date: str = ''
    hours_missing: int = 0  # station-hours without a row (e.g. 23-hour days), read as missing with flag 'a'
    negative_values: int = 0  # values below 0 (-1 with flag 'x'), read as missing
    flags: dict[str, int] = field(default_factory=dict)  # flag -> hourly values of KFZ with it, both directions


def _read_table(path: Path) -> pd.DataFrame:
    """The station table as strings; a zip holds one csv. Annual files use ';', v1's merged files ','."""
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith('.csv'))
            text = z.read(name).decode('ISO-8859-1')
    else:
        text = path.read_bytes().decode('ISO-8859-1')
    sep = ';' if ';' in text[:text.index('\n')] else ','
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, skipinitialspace=True)
    return df.drop(columns=[c for c in df.columns if c.startswith('Unnamed')]).apply(lambda s: s.str.strip())


def read_station_table(path: str | Path, stations: set[str] | None = None) -> tuple[pd.DataFrame, BastReport]:
    """Hourly counts per detector (direction) and v1 class as RAW_COUNTS rows, with the flag of every hour.

    Volumes of columns that map to the same class are added; the daily value is the sum of the hours (v1).

    Args:
        stations: only these station numbers (Zst), None = all

    Raises:
        ValueError: if columns are missing, a station-hour appears twice or a flag is unknown
    """
    df = _read_table(Path(path))
    if stations is not None:
        df = df[df['Zst'].isin(stations)]
    return _table_to_counts(df, str(path))


def _table_to_counts(df: pd.DataFrame, name: str) -> tuple[pd.DataFrame, BastReport]:
    """Station table (strings; optional column `type` with the classification) -> RAW_COUNTS rows."""
    columns = [f'{c}_R{r}' for parts in CLASSES.values() for c in parts for r in (1, 2)]
    missing = [c for c in ['Zst', 'Datum', 'Stunde'] + columns + [f'K_{c}' for c in columns] if c not in df.columns]
    if missing:
        raise ValueError(f'{name}: missing columns {missing}')
    if df.duplicated(['Zst', 'Datum', 'Stunde']).any():
        raise ValueError(f'{name}: station-hours appear more than once')
    if df.empty:
        return RAW_COUNTS.validate(pd.DataFrame(columns=list(RAW_COUNTS.columns))), BastReport()

    dates = pd.to_datetime(df['Datum'], format='%y%m%d')
    hour = df['Stunde'].astype(int).to_numpy() - 1  # hour ending at 01:00 .. 24:00
    codes, uniques = pd.MultiIndex.from_arrays([df['Zst'], dates]).factorize()
    station_days = pd.MultiIndex.from_tuples(list(uniques))
    n = len(station_days)
    report = BastReport(stations=df['Zst'].nunique(), station_days=n, first_date=str(dates.min().date()),
                        last_date=str(dates.max().date()), hours_missing=n * 24 - len(df))
    report.flags = {str(k): int(v) for k, v in pd.concat([df['K_KFZ_R1'], df['K_KFZ_R2']]).value_counts().sort_index().items()}
    report.negative_values = int((df[columns].astype(float) < 0).sum().sum())
    detector_type = None
    if 'type' in df.columns:
        types = pd.Series(df['type'].to_numpy()).groupby(codes).first()
        detector_type = types.reindex(range(n)).to_numpy()

    rank = {f: i for i, f in enumerate(FLAG_ORDER)}
    frames = []
    for direction in (1, 2):
        for vehicle_class, parts in CLASSES.items():
            columns = np.array([df[f'{p}_R{direction}'].astype(float).to_numpy() for p in parts])
            values = columns.sum(axis=0)
            # -1 (flag 'x') marks a column the station doesn't count; a class with such a part is missing. Summing
            # would give e.g. PC = PmA - 1 at 5+1 stations, which don't count Pkw (fixed in ANNUAL_READER_VERSION 2)
            values[(columns < 0).any(axis=0)] = np.nan
            flag_rank = np.max([df[f'K_{p}_R{direction}'].map(rank).to_numpy() for p in parts], axis=0)
            if np.isnan(flag_rank.astype(float)).any():
                raise ValueError(f'{name}: unknown flags in {parts} R{direction}')
            hours = np.full((n, 24), np.nan)
            hours[codes, hour] = values
            ranks = np.full((n, 24), rank['a'])  # an hour without a row is missing
            ranks[codes, hour] = flag_rank
            flags = np.array(list(FLAG_ORDER))[ranks]
            frames.append(pd.DataFrame({
                'source': SOURCE,
                'detector_id': station_days.get_level_values(0) + str(direction),
                'detector_type': detector_type,
                'date': station_days.get_level_values(1),
                'vehicle_class': vehicle_class,
                'metric': 'volume',
                'daily_value': np.nansum(hours, axis=1),
                **dict(zip(HOURS, hours.T)),
                'flags': [''.join(f) for f in flags],
            }))
    counts = pd.concat(frames, ignore_index=True)
    counts['date'] = counts['date'].astype('datetime64[us]')
    return RAW_COUNTS.validate(counts), report


# Raw data (Rohdaten): one fixed-width file per station and month, see DZ-Beschreibung.pdf and docs/bast_counts_README.md
RAW_FILE = re.compile(r'(?:^|/)([A-Z]{2})(\d{4})(?:_\d)?\.(\d{2})([1-9abc])$')
# names in the file -> columns of the station table; absent classes are read as not counted (-1, 'x')
_RAW_COLUMNS = {'KFZ': 'KFZ', 'SV': 'Lkw', 'Lkw': 'Lkw', 'Mot': 'Mot', 'Pkw': 'Pkw', 'Lfw': 'Lfw', 'PmA': 'PmA',
                'Bus': 'Bus', 'LoA': 'LoA', 'LmA': 'Lzg', 'Sat': 'Lzg', 'Lzg': 'Lzg', 'PLZ': 'PLZ', 'Son': 'Son'}
_CLASSIFICATION = {9: '8+1', 6: '5+1', 0: None}


def _parse_raw_file(text: str, name: str) -> pd.DataFrame:
    """One station-month in the fixed-width format -> rows of the station table (strings).

    Lanes are added per direction, LmA + Sat give Lzg (as in the annual table and v1). Records inserted at the
    clock change (status 'i', all values 0) are skipped as in v1, so that day has 23 hours.
    """
    lines = text.splitlines()
    head, lanes, config = lines[0], lines[1], lines[2]
    if not (head.startswith('H') and lanes.startswith('R') and config.startswith('S')):
        raise ValueError(f'{name}: expected the header lines H, R and S')
    station = head[5:9]
    lanes_per_direction = (int(lanes[1:3]), int(lanes[4:6]))
    n_groups, n_classes = int(config[1:3]), int(config[4:6])
    names = config[7:].replace(';', ' ').split()
    if len(names) != n_groups + n_classes:
        raise ValueError(f'{name}: {len(names)} names for {n_groups} groups and {n_classes} classes')
    unknown = set(names) - set(_RAW_COLUMNS)
    if unknown:
        raise ValueError(f'{name}: unknown vehicle classes {sorted(unknown)}')
    if n_classes:
        classification = _CLASSIFICATION.get(n_classes)
    else:
        classification = '2' if n_groups == 2 else '1'
    n_lanes = sum(lanes_per_direction)
    direction = np.repeat([1, 2], lanes_per_direction)
    # position of every value: groups for every lane, then classes for every lane
    fields = [(names[g], direction[lane]) for lane in range(n_lanes) for g in range(n_groups)] + \
             [(names[n_groups + c], direction[lane]) for lane in range(n_lanes) for c in range(n_classes)]

    body = [line for line in lines[3:] if len(line) >= 12 and line[:6].isdigit()]
    body = [line for line in body if line[6] != 'i']
    width = 12 + 6 * len(fields)
    short = [line for line in body if len(line) < width]
    if short:
        raise ValueError(f'{name}: {len(short)} hour lines shorter than {width} characters, first: {short[0]!r}')
    rank = {f: i for i, f in enumerate(FLAG_ORDER)}
    values = np.array([[int(line[13 + 6 * k:17 + 6 * k]) for k in range(len(fields))] for line in body])
    flags = np.array([[line[17 + 6 * k] for k in range(len(fields))] for line in body])
    unknown_flags = set(np.unique(flags)) - set(FLAG_ORDER)
    if unknown_flags:
        raise ValueError(f'{name}: unknown flags {sorted(unknown_flags)}')

    table = {'Zst': station, 'Datum': [line[:6] for line in body], 'Stunde': [line[7:9] for line in body],
             'type': classification}
    for column in sorted(set(CLASSES_COLUMNS)):
        for d in (1, 2):
            picked = [k for k, (n, dd) in enumerate(fields) if _RAW_COLUMNS[n] == column and dd == d]
            if not picked:
                table[f'{column}_R{d}'] = '-1'
                table[f'K_{column}_R{d}'] = 'x'
                continue
            table[f'{column}_R{d}'] = values[:, picked].sum(axis=1).astype(str)
            worst = np.max(np.vectorize(rank.get)(flags[:, picked]), axis=1)
            table[f'K_{column}_R{d}'] = np.array(list(FLAG_ORDER))[worst]
    return pd.DataFrame(table)


CLASSES_COLUMNS = [c for parts in CLASSES.values() for c in parts]
# part of the batch parameters of the annual files, so that a reader fix re-ingests them. 2: a class with a part that
# isn't counted (-1) is missing instead of the sum of its parts (2026-11-16)
ANNUAL_READER_VERSION = 2


def _raw_members(archive: zipfile.ZipFile, stations: set[str] | None):
    """(name, text) of the station files in an archive, also inside nested zips (older yearly archives)."""
    for member in archive.namelist():
        if member.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(archive.read(member))) as inner:
                yield from _raw_members(inner, stations)
            continue
        match = RAW_FILE.search(member)
        if match and (stations is None or match.group(2) in stations):
            yield member, archive.read(member).decode('ISO-8859-1')


def read_raw_archive(path: str | Path, stations: set[str] | None = None) -> tuple[pd.DataFrame, BastReport]:
    """Counts of a raw-data archive (DZ_<year>[_<month>]_Rohdaten.zip) as RAW_COUNTS rows, see _parse_raw_file.

    Args:
        stations: only these station numbers, None = all stations in Germany
    """
    with zipfile.ZipFile(path) as archive:
        tables = [_parse_raw_file(text, name) for name, text in _raw_members(archive, stations)]
    if not tables:
        raise ValueError(f'{path}: no station files' + (f' of the stations {sorted(stations)}' if stations else ''))
    # a station can come in two files of one month after a change of its structure (version suffix _1)
    table = pd.concat(tables, ignore_index=True)
    return _table_to_counts(table, str(path))


def read_locations(path: str | Path, model_link_ids: dict[str, set[int]]) -> tuple[pd.DataFrame, dict[str, list[int]]]:
    """Counter links from the matched locations (bast_locations_selected.gpkg: DETEKTOR_ID, road_link_id)."""
    locations = gpd.read_file(path, columns=['DETEKTOR_ID', 'road_link_id'], ignore_geometry=True)
    pairs = locations.rename(columns={'DETEKTOR_ID': 'detector_id'}).dropna(subset=['road_link_id'])
    return links_per_model(pairs, SOURCE, model_link_ids)


# ---- downloads (counting_data/bast/download_bast_data*.ipynb) ----

RAW_LINK = re.compile(r'href="([^"]*/DZ_(\d{4})(?:_(\d{2}))?_Rohdaten\.zip)"')


def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=2,
                                                            status_forcelist=[429, 500, 502, 503, 504])))
    return session


def _save(response, target: Path) -> Path:
    """Streams a response to target via a .part file and checks that it is a zip archive."""
    part = target.with_name(target.name + '.part')
    with open(part, 'wb') as f:
        f.writelines(response.iter_content(1 << 20))
    if not zipfile.is_zipfile(part):
        part.unlink()
        raise ValueError(f'{response.url} did not return a zip archive')
    part.replace(target)
    return target


def download_annual(url_template: str, station: str, year: int, directory: Path) -> Path | None:
    """Annual station file as directory/zst<station>_<year>.zip; None if BASt has none (404).

    An existing file is kept: annual files are final.
    """
    target = directory / f'zst{station}_{year}.zip'
    if target.exists():
        return target
    directory.mkdir(parents=True, exist_ok=True)
    with _session().get(url_template.format(year=year, station=station), stream=True, timeout=120) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _save(response, target)


def raw_links(page_url: str) -> dict[str, str]:
    """Raw-data archives listed on the BASt page: file name (DZ_<year>[_<month>]_Rohdaten.zip) -> URL.
    The links point to a Nextcloud share whose tokens change, so they must be read from the page."""
    response = _session().get(page_url, timeout=60)
    response.raise_for_status()
    return {url.rsplit('/', 1)[1]: url for url, _, _ in RAW_LINK.findall(response.text)}


def download_raw(url: str, directory: Path) -> Path:
    """Raw-data archive as directory/<file name>, replacing an earlier download: BASt revises raw data."""
    directory.mkdir(parents=True, exist_ok=True)
    with _session().get(url, stream=True, timeout=600) as response:
        response.raise_for_status()
        return _save(response, directory / url.rsplit('/', 1)[1])
