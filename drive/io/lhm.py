"""Landeshauptstadt München (LHM) counting stations (MST): raw detector exports and locations.

Port of v1 data_preprocessing/12. The exports (Quartalsexport_/Jahresexport_MST_Detektoren_*.csv) have
one row per detector, day and ART (count or speed type) with a daily value and 24 hourly columns.
All detectors are read; which ones are used follows from the counter links (locations file).
"""

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from drive.io.counter_links import links_per_model
from drive.schemas import HOURS, RAW_COUNTS

SOURCE = 'LHM'
_ID_COLUMNS = ['MST', 'MQ', 'DETEKTOR_ID', 'DATUM', 'ART', 'TAGES_SUMME']
_HOUR_COLUMNS = [f'{h:02d}:00-{h + 1:02d}:00' for h in range(24)]

# counts per class (v1); the classes are disjoint and add up to QKFZ. QLKW are trucks without trailer.
VOLUME_CLASSES = {'QKFZ': 'SUM', 'QPKW': 'PC', 'QPKWA': 'PC', 'QLFW': 'LCV', 'QLKW': 'HGV', 'QLKWA': 'HGV',
                  'QSATTEL_KFZ': 'HGV', 'QBUS': 'BUS', 'QKRAD': 'MOT'}
# mean speeds (km/h); v1 kept these three
SPEED_CLASSES = {'VPKW': 'PC', 'VLKW': 'HGV', 'VKFZ': 'VKFZ'}


@dataclass
class LhmReport:
    rows: int = 0
    detectors: int = 0
    first_date: str = ''
    last_date: str = ''
    unused_art: dict[str, int] = field(default_factory=dict)  # ART -> rows not read (e.g. QNK_KFZ, BIKE)
    negative_values: dict[str, int] = field(default_factory=dict)  # ART -> values below 0, read as missing


def read_export(path: str | Path) -> tuple[pd.DataFrame, LhmReport]:
    """One detector export as RAW_COUNTS rows (volumes per class and speeds).

    Volumes of ARTs that map to the same class are added (v1). Negative values are read as missing
    and counted in the report. The daily value of a speed is not
    an average of the hours, so it is left empty (v1 wrote 0). detector_type is left empty: v1 wrote
    '8+1' for every detector.

    Raises:
        ValueError: if the columns are not those of an MST detector export
    """
    df = pd.read_csv(path, sep=';', decimal=',', encoding='ISO-8859-1', dtype={'DETEKTOR_ID': str})
    expected = _ID_COLUMNS + _HOUR_COLUMNS
    if list(df.columns[:len(expected)]) != expected:
        raise ValueError(f'{path}: unexpected columns {list(df.columns[:8])}...')
    df = df[expected]
    report = LhmReport(rows=len(df), detectors=df['DETEKTOR_ID'].nunique())
    used = df['ART'].isin(list(VOLUME_CLASSES) + list(SPEED_CLASSES))
    report.unused_art = {str(k): int(v) for k, v in df.loc[~used, 'ART'].value_counts().sort_index().items()}

    df = df.rename(columns={'DETEKTOR_ID': 'detector_id', 'TAGES_SUMME': 'daily_value', **dict(zip(_HOUR_COLUMNS, HOURS))})
    df['date'] = pd.to_datetime(df['DATUM'], format='%d.%m.%Y')
    report.first_date, report.last_date = str(df['date'].min().date()), str(df['date'].max().date())
    values = ['daily_value'] + HOURS
    df[values] = df[values].astype(float)
    negative = df[values] < 0  # only seen in VPKW speeds of unmatched detectors (2022, 2024, 2025)
    per_art = negative.sum(axis=1).groupby(df['ART']).sum()
    report.negative_values = {str(k): int(v) for k, v in per_art[per_art > 0].items()}
    df[values] = df[values].mask(negative)
    key = ['date', 'detector_id', 'vehicle_class']

    volume = df[df['ART'].isin(list(VOLUME_CLASSES))].assign(vehicle_class=lambda d: d['ART'].map(VOLUME_CLASSES))
    volume = volume.groupby(key, as_index=False)[values].sum().assign(metric='volume')
    speed = df[df['ART'].isin(list(SPEED_CLASSES))].assign(vehicle_class=lambda d: d['ART'].map(SPEED_CLASSES))
    speed = speed.groupby(key, as_index=False)[HOURS].mean().assign(metric='speed', daily_value=np.nan)

    counts = pd.concat([volume, speed], ignore_index=True)
    counts = counts.assign(source=SOURCE, detector_type=None)
    columns = ['source', 'detector_id', 'detector_type', 'date', 'vehicle_class', 'metric', 'daily_value'] + HOURS
    return RAW_COUNTS.validate(counts[columns]), report


def read_locations(path: str | Path, model_link_ids: dict[str, set[int]]) -> tuple[pd.DataFrame, dict[str, list[int]]]:
    """Counter links from the matched locations (mst_locations_selected.gpkg: DETEKTOR_ID, road_link_id)."""
    locations = gpd.read_file(path, columns=['DETEKTOR_ID', 'road_link_id'], ignore_geometry=True)
    pairs = locations.rename(columns={'DETEKTOR_ID': 'detector_id'}).dropna(subset=['road_link_id'])
    return links_per_model(pairs, SOURCE, model_link_ids)
