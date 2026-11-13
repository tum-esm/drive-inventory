"""BASt automatic permanent counting stations (Dauerzählstellen) on federal roads: hourly counts and locations.

Port of v1 data_preprocessing/11 and counting_data/bast/download_bast_data*.ipynb. Format reference: BASt,
"BASt-Bestandsbandformat für Verkehrsmengendaten, Version 2004" (DZ-Beschreibung.pdf on the download page).

The station table (annual files zst<station>_<year>.csv, one row per station and hour, both directions as
columns `<class>_R1/_R2` with a flag `K_<class>_R1/_R2`) is read into one detector per direction:
detector_id = station + '1' or '2' (v1).
"""

import io
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


def read_station_table(path: str | Path) -> tuple[pd.DataFrame, BastReport]:
    """Hourly counts per detector (direction) and v1 class as RAW_COUNTS rows, with the flag of every hour.

    Volumes of columns that map to the same class are added; the daily value is the sum of the hours (v1).

    Raises:
        ValueError: if columns are missing or a station-hour appears twice
    """
    df = _read_table(Path(path))
    columns = [f'{c}_R{r}' for parts in CLASSES.values() for c in parts for r in (1, 2)]
    missing = [c for c in ['Zst', 'Datum', 'Stunde'] + columns + [f'K_{c}' for c in columns] if c not in df.columns]
    if missing:
        raise ValueError(f'{path}: missing columns {missing}')
    if df.duplicated(['Zst', 'Datum', 'Stunde']).any():
        raise ValueError(f'{path}: station-hours appear more than once')

    dates = pd.to_datetime(df['Datum'], format='%y%m%d')
    hour = df['Stunde'].astype(int).to_numpy() - 1  # hour ending at 01:00 .. 24:00
    codes, uniques = pd.MultiIndex.from_arrays([df['Zst'], dates]).factorize()
    station_days = pd.MultiIndex.from_tuples(list(uniques))
    n = len(station_days)
    report = BastReport(stations=df['Zst'].nunique(), station_days=n, first_date=str(dates.min().date()),
                        last_date=str(dates.max().date()), hours_missing=n * 24 - len(df))
    report.flags = {str(k): int(v) for k, v in pd.concat([df['K_KFZ_R1'], df['K_KFZ_R2']]).value_counts().sort_index().items()}
    report.negative_values = int((df[columns].astype(float) < 0).sum().sum())

    rank = {f: i for i, f in enumerate(FLAG_ORDER)}
    frames = []
    for direction in (1, 2):
        for vehicle_class, parts in CLASSES.items():
            values = np.sum([df[f'{p}_R{direction}'].astype(float).to_numpy() for p in parts], axis=0)
            values[values < 0] = np.nan  # -1 with flag 'x'
            flag_rank = np.max([df[f'K_{p}_R{direction}'].map(rank).to_numpy() for p in parts], axis=0)
            if np.isnan(flag_rank.astype(float)).any():
                raise ValueError(f'{path}: unknown flags in {parts} R{direction}')
            hours = np.full((n, 24), np.nan)
            hours[codes, hour] = values
            ranks = np.full((n, 24), rank['a'])  # an hour without a row is missing
            ranks[codes, hour] = flag_rank
            flags = np.array(list(FLAG_ORDER))[ranks]
            frames.append(pd.DataFrame({
                'source': SOURCE,
                'detector_id': station_days.get_level_values(0) + str(direction),
                'detector_type': None,
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


def read_locations(path: str | Path, model_link_ids: dict[str, set[int]]) -> tuple[pd.DataFrame, dict[str, list[int]]]:
    """Counter links from the matched locations (bast_locations_selected.gpkg: DETEKTOR_ID, road_link_id)."""
    locations = gpd.read_file(path, columns=['DETEKTOR_ID', 'road_link_id'], ignore_geometry=True)
    pairs = locations.rename(columns={'DETEKTOR_ID': 'detector_id'}).dropna(subset=['road_link_id'])
    return links_per_model(pairs, SOURCE, model_link_ids)
