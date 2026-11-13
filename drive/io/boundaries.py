"""BKG VG250 administrative boundaries of Germany (open data, dl-de/by-2-0).

The archive holds one GeoPackage with a layer per level (vg250_lan states, vg250_krs districts,
vg250_gem municipalities, ...). A download is kept unchanged as `vg250_<status date>.zip`.
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import pyogrio
import requests
import shapely

from drive.schemas import BOUNDARIES

# GF (Geofaktor): 1/2 water, 3/4 land, each without/with lower-level structure
LAND = [3, 4]


def _status_date(archive: zipfile.ZipFile) -> str:
    """Status date of the data (dokumentation/aktualitaet.txt, dd.mm.yyyy) as yyyy-mm-dd."""
    name = next(n for n in archive.namelist() if n.endswith('aktualitaet.txt'))
    day, month, year = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', archive.read(name).decode()).groups()  # type: ignore[union-attr]
    return f'{year}-{month}-{day}'


def download(url: str, directory: Path) -> Path:
    """Downloads the archive and keeps it as directory/vg250_<status date>.zip, unless that file exists.

    Returns:
        path of the archive for this status date
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (requests.get(url, stream=True, timeout=300) as response,
          tempfile.NamedTemporaryFile(dir=directory, suffix='.part', delete=False) as tmp):
        part = Path(tmp.name)
        try:
            response.raise_for_status()
            shutil.copyfileobj(response.raw, tmp)
        except Exception:
            part.unlink()
            raise
    with zipfile.ZipFile(part) as archive:
        target = directory / f'vg250_{_status_date(archive)}.zip'
    if target.exists():
        part.unlink()
    else:
        part.rename(target)
    return target


def read_vg250(path: Path, levels: list[str]) -> pd.DataFrame:
    """Rows of the requested levels (e.g. 'lan', 'krs', 'gem'), contract drive.schemas.BOUNDARIES."""
    with zipfile.ZipFile(path) as archive:
        status = _status_date(archive)
        gpkg = next(n for n in archive.namelist() if n.endswith('.gpkg'))
        with tempfile.TemporaryDirectory() as tmp:
            file = archive.extract(gpkg, tmp)
            frames = []
            for level in levels:
                df = pyogrio.read_dataframe(file, layer=f'vg250_{level}', columns=['AGS', 'GEN', 'BEZ', 'GF', 'BEGINN'])
                if df.crs is None:
                    raise ValueError(f'Layer vg250_{level} of {path.name} has no CRS')
                frames.append(pd.DataFrame({
                    'source': 'VG250',
                    'status_date': pd.Timestamp(status),
                    'level': level,
                    'ags': df['AGS'],
                    'name': df['GEN'],
                    'kind': df['BEZ'],
                    'gf': df['GF'].astype('int64'),
                    'part': df.groupby(['AGS', 'GF']).cumcount(),
                    'valid_from': pd.to_datetime(df['BEGINN']),
                    'crs': df.crs.to_string(),
                    'geometry': shapely.to_wkb(df.geometry.values),
                }))
    return BOUNDARIES.validate(pd.concat(frames, ignore_index=True))
