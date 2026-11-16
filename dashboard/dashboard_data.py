"""Data access of the dashboard (spec R27, D33): read-only on the store, the drive pipeline and the run outputs.

No calculation logic of its own (D11). The scaling results come from `pipeline.load_activity`; everything
else is read from the store or from the files `drive run` and `scripts/run_series.py` write.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from drive import store
from drive.config import DriveConfig
from drive.domain.calendar import SATURDAY, SUNDAY_HOLIDAY, WEEKDAY
from drive.pipeline import load_activity, load_counter_links

RUN_FILE = re.compile(r'^summary_(?P<model>visum\d{4})_(?P<year>\d{4})_hbefa(?P<hbefa>\d+)_batch(?P<batch>\d+)\.csv$')
DAY_GROUP_NAMES = {WEEKDAY: 'Weekday (Mon-Fri)', SATURDAY: 'Saturday', SUNDAY_HOLIDAY: 'Sunday/holiday'}
ROAD_TYPE_COLOURS = {
    'Motorway-Nat': [180, 30, 45],
    'Motorway-City': [220, 90, 60],
    'TrunkRoad/Primary-National': [235, 140, 30],
    'TrunkRoad/Primary-City': [240, 190, 40],
    'Distributor/Secondary': [60, 130, 200],
    'Local/Collector': [110, 170, 120],
    'Access-residential': [150, 150, 150],
}


@dataclass(frozen=True)
class Run:
    """One run written by `drive run` / `scripts/run_series.py`, identified by its file stem."""
    model: str
    year: int
    stem: str
    folder: Path

    @property
    def label(self) -> str:
        return f'{self.year} ({self.model})'


def find_runs(folder: Path) -> list[Run]:
    """Runs in a results folder, the latest store batch per traffic model and year."""
    latest: dict[tuple[str, int], tuple[int, str]] = {}
    for path in folder.glob('summary_*.csv'):
        match = RUN_FILE.match(path.name)
        if match is None:
            continue
        key = (match['model'], int(match['year']))
        batch = int(match['batch'])
        if key not in latest or batch > latest[key][0]:
            latest[key] = (batch, path.stem.removeprefix('summary_'))
    runs = [Run(model, year, stem, folder) for (model, year), (_, stem) in latest.items()]
    return sorted(runs, key=lambda r: (r.year, r.model))


def to_wgs84_paths(frame: gpd.GeoDataFrame) -> list[list[list[float]]]:
    """Line geometries as lists of [lon, lat] for pydeck (first part of multi-lines, z dropped)."""
    lines = frame.to_crs(4326).geometry
    paths = []
    for geometry in lines:
        if geometry.geom_type == 'MultiLineString':
            geometry = max(geometry.geoms, key=lambda g: g.length)
        paths.append([[x, y] for x, y, *_ in geometry.coords])
    return paths


def model_links(config: DriveConfig, traffic_model: str) -> gpd.GeoDataFrame:
    """Links of a traffic model, one row per road link (directions summed): road type, dtv_SUM, geometry."""
    links = store.read_links(config.paths.store, traffic_model)
    total = links.groupby('road_link_id')['dtv_SUM'].sum()
    first = links.drop_duplicates('road_link_id').set_index('road_link_id')
    frame = gpd.GeoDataFrame({'road_type': first['road_type'], 'dtv_SUM': total.reindex(first.index)},
                             geometry=first.geometry, crs=links.crs).reset_index()
    return frame


def counters(config: DriveConfig, traffic_model: str) -> gpd.GeoDataFrame:
    """Detectors at the midpoint of their matched link (overrides applied): source, detector_id, road_link_id."""
    model_config = config.model_copy(deep=True)
    model_config.run.traffic_model = traffic_model
    version = store.resolve_version(config.paths.store, config.run.data_version)
    matching, _ = load_counter_links(model_config, version)
    links = store.read_links(config.paths.store, traffic_model).drop_duplicates('road_link_id').set_index('road_link_id')
    points = links.geometry.reindex(matching['road_link_id']).interpolate(0.5, normalized=True)
    return gpd.GeoDataFrame(matching.reset_index(drop=True), geometry=points.to_numpy(), crs=links.crs)


def activity(config: DriveConfig, traffic_model: str, reference_year: int):
    """Activity (scaling, shares, diurnal cycles) of a traffic model, from the drive pipeline."""
    model_config = config.model_copy(deep=True)
    model_config.run.traffic_model = traffic_model
    model_config.run.reference_year = reference_year
    act, report, _ = load_activity(model_config)
    return act, report


def summaries(runs: list[Run]) -> pd.DataFrame:
    """summary_<stem>.csv of all runs with run label, year and model: t per kind, road type, class, component."""
    frames = [pd.read_csv(r.folder / f'summary_{r.stem}.csv').assign(run=r.label, year=r.year, model=r.model)
              for r in runs]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def vehicle_km(runs: list[Run]) -> pd.DataFrame:
    """vkt_<stem>.csv of all runs that have one."""
    frames = [pd.read_csv(r.folder / f'vkt_{r.stem}.csv').assign(run=r.label, year=r.year, model=r.model)
              for r in runs if (r.folder / f'vkt_{r.stem}.csv').exists()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def line_sources(run: Run, kind: str, component: str) -> gpd.GeoDataFrame:
    """g/km of one component per link piece, summed over the vehicle classes; kind hot, cold or total."""
    path = run.folder / f'linesource_{run.stem}.gpkg'
    layers = ['hot', 'cold'] if kind == 'total' else [kind]
    frames = []
    for layer in layers:
        frame = gpd.read_file(path, layer=layer)
        columns = [c for c in frame.columns if c.endswith(f'_{component}') and not c.startswith('vkt_')]
        frames.append(frame.assign(value=frame[columns].sum(axis=1) if columns else 0.0))
    result = frames[0][['road_link_id', 'from_node', 'piece', 'road_type', 'length_km', 'value', 'geometry']].copy()
    for other in frames[1:]:
        result['value'] = result['value'] + other['value'].to_numpy()
    return result


def grid(run: Run, grid_name: str, kind: str, component: str) -> gpd.GeoDataFrame:
    """kg of one component per grid cell; kind hot, cold or total."""
    frame = gpd.read_file(run.folder / f'grid_{grid_name}_{run.stem}.gpkg', layer=kind)
    values = frame[component] if component in frame else pd.Series(0.0, index=frame.index)
    return gpd.GeoDataFrame({'value': values}, geometry=frame.geometry, crs=frame.crs)


def grid_names(run: Run) -> list[str]:
    prefix, suffix = 'grid_', f'_{run.stem}.gpkg'
    return sorted(p.name.removeprefix(prefix).removesuffix(suffix) for p in run.folder.glob(f'grid_*{suffix}'))


def colour_scale(values: np.ndarray, log: bool = True) -> np.ndarray:
    """RGBA per value on a yellow-red scale, quantile-normalised (2nd to 98th percentile), optionally on log10."""
    v = np.asarray(values, dtype=float)
    positive = v > 0
    x = np.zeros_like(v)
    if positive.any():
        data = np.log10(v[positive]) if log else v[positive]
        low, high = np.percentile(data, [2, 98])
        x[positive] = np.clip((data - low) / (high - low if high > low else 1.0), 0, 1)
    start, end = np.array([255, 237, 160]), np.array([177, 0, 38])
    rgb = start + (end - start) * x[:, None]
    alpha = np.where(positive, 200, 0)
    return np.column_stack([rgb, alpha]).astype(int)
