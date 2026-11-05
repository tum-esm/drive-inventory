"""Adapter for HBEFA emission factor tables (raw API results saved as parquet).

One naming scheme (R2): `{year}_{category}_{aggregation}_v{hbefa_version}.parquet`, for example
`2025_hot_single_ts_v501007.parquet`. The tables don't contain the HBEFA version, so it comes
from the file name; year and category are checked against the content.

The API client that downloads these files follows later (R20).
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from drive.schemas import EMISSION_FACTORS

_FILE_NAME = re.compile(r'^(\d{4})_(hot|start)_(single_ts|aggregate_ts)_v(\d+)\.parquet$')

VEHICLE_CLASSES = {'pass. car': 'PC', 'LCV': 'LCV', 'HGV': 'HGV', 'motorcycle': 'MOT', 'coach': 'BUS'}

_COLUMNS = {
    'Reference year': 'reference_year',
    'Process scope': 'process_scope',
    'Weight': 'weight',
    'Emission category': 'emission_category',
    'Pollutant': 'pollutant',
    'Vehicle category': 'vehicle_class',
    'Traffic situation': 'traffic_situation',
    'Aggr. traffic situation': 'traffic_situation',
    'Road category': 'road_category',
    'Gradient': 'gradient',
    'Ambient cond. pattern': 'ambient_pattern',
    'EF unit': 'ef_unit',
    'v': 'speed',
    'v_0%': 'speed_0',
    'v_100%': 'speed_100',
    'EFA': 'efa',
    'EFA_0%': 'efa_0',
    'EFA_100%': 'efa_100',
    'Cum. mileage': 'cum_mileage',
    'Traffic scenario': 'traffic_scenario',
    'Country': 'country',
}


@dataclass(frozen=True)
class EfFile:
    path: Path
    reference_year: int
    emission_category: str
    aggregation: str
    hbefa_version: int


def parse_file_name(path: str | Path) -> EfFile:
    """Raises ValueError if the file name doesn't follow the naming scheme."""
    path = Path(path)
    match = _FILE_NAME.match(path.name)
    if match is None:
        raise ValueError(f'{path.name} does not match {{year}}_{{category}}_{{aggregation}}_v{{version}}.parquet')
    year, category, aggregation, version = match.groups()
    return EfFile(path, int(year), category, aggregation, int(version))


def find_files(directory: str | Path, hbefa_version: int) -> list[EfFile]:
    """All tables of one HBEFA version in a directory.

    Raises:
        ValueError: if a parquet file doesn't follow the naming scheme, or no table has this version
    """
    files = [parse_file_name(p) for p in sorted(Path(directory).glob('*.parquet'))]
    files = [f for f in files if f.hbefa_version == hbefa_version]
    if not files:
        raise ValueError(f'No emission factor tables of HBEFA version {hbefa_version} in {directory}')
    return files


def read_table(file: EfFile) -> pd.DataFrame:
    """Reads one table into the EMISSION_FACTORS contract.

    Raises:
        ValueError: on unknown columns, unmapped vehicle categories or content that
            contradicts the file name
        pandera.errors.SchemaError: if a key is repeated
    """
    raw = pd.read_parquet(file.path)
    name = file.path.name

    unknown = set(raw.columns) - set(_COLUMNS)
    if unknown:
        raise ValueError(f'{name}: unknown columns {sorted(unknown)}')
    df = raw.rename(columns=_COLUMNS)
    for column, expected in [('reference_year', file.reference_year), ('emission_category', file.emission_category)]:
        found = df[column].unique().tolist()
        if found != [expected]:
            raise ValueError(f'{name}: the file name says {column} {expected}, the table contains {found}')

    unmapped = set(df['vehicle_class']) - set(VEHICLE_CLASSES)
    if unmapped:
        raise ValueError(f'{name}: unmapped vehicle categories {sorted(unmapped)}')
    df['vehicle_class'] = df['vehicle_class'].map(VEHICLE_CLASSES)

    df['hbefa_version'] = file.hbefa_version
    df['aggregation'] = file.aggregation
    for column in ['traffic_situation', 'gradient']:  # start tables have neither, aggregate tables no gradient
        if column not in df:
            df[column] = None

    return EMISSION_FACTORS.validate(df[list(EMISSION_FACTORS.columns)])
