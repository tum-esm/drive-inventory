"""Compare `drive ingest visum` with the output of v1 preprocessing 21 and 21v2.

Usage: uv run python scripts/compare_v1_visum.py [configs/munich_2025.yaml]

Reads the links and zones from the store and compares them row by row with v1's
visum_links_<year>.gpkg and visum_zones_<year>.gpkg. They must be identical.
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

from drive import store
from drive.config import load_config


def compare(v1: gpd.GeoDataFrame, v2: gpd.GeoDataFrame, name: str) -> list[str]:
    if len(v1) != len(v2):
        return [f'{name}: {len(v1)} rows in v1, {len(v2)} in v2']
    problems = []
    if v1.crs != v2.crs:
        problems.append(f'{name}: CRS {v1.crs} vs {v2.crs}')
    if not shapely.equals_exact(v1.geometry.values, v2.geometry.values, 0).all():
        problems.append(f'{name}: geometry differs')
    for column in v1.columns.drop('geometry'):
        different = v1[column].to_numpy() != v2[column].to_numpy()
        if different.any():
            problems.append(f'{name}: {column} differs in {different.sum()} rows')
    return problems


def main(config_path: str = 'configs/munich_2025.yaml') -> int:
    config = load_config(config_path)
    problems = []
    for model, c in config.traffic_models.items():
        year = model.removeprefix('visum')
        folder = Path(c.links).parent
        links = store.read_links(config.paths.store, model)
        zones = store.read_zones(config.paths.store, model)
        problems += compare(gpd.read_file(folder / f'visum_links_{year}.gpkg'), links, f'{model} links')
        problems += compare(gpd.read_file(folder / f'visum_zones_{year}.gpkg'), zones, f'{model} zones')

        ratio = links['visum_length_km'] * 1000 / links.length
        print(f'{model}: {len(links)} links, batch {links["batch_id"].iloc[0]}; {len(zones)} zones, '
              f'batch {zones["batch_id"].iloc[0]}; model length / geometry length: median '
              f'{np.median(ratio):.3f}, outside 0.9-1.1 on {((ratio < 0.9) | (ratio > 1.1)).sum()} links')

    print('\n'.join(problems) if problems else 'OK: identical to v1')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
