"""Output products of a run (spec R12): line-source GeoPackage and summary table.

Units: the line sources hold g/km per link piece over the run's period (one year), as v1's
`linesource_*.gpkg`; the summary holds tonnes per period. Totals of a component are the sum of
g/km x length over the link pieces, so the line sources and the summary add up to the same numbers.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

KEYS = ['road_link_id', 'from_node', 'piece', 'road_type', 'scaling_road_type', 'length_km']


def emission_columns(table: pd.DataFrame) -> list[str]:
    """The {vehicle_class}_{component} columns of a result table (hot_results, cold_results)."""
    return [c for c in table.columns if c not in KEYS and c != 'geometry']


def line_sources(links: gpd.GeoDataFrame, table: pd.DataFrame) -> gpd.GeoDataFrame:
    """A result table (g/km per link piece, index as `links`) with the link geometry."""
    if not table.index.equals(links.index):
        raise ValueError('The result table and the links must have the same index')
    return gpd.GeoDataFrame(table, geometry=links.geometry, crs=links.crs)


def write_line_sources(path: Path, layers: dict[str, gpd.GeoDataFrame]) -> None:
    """One GeoPackage with one layer per emission kind (hot, cold); replaces an existing file."""
    path.unlink(missing_ok=True)
    for name, frame in layers.items():
        frame.to_file(path, layer=name, driver='GPKG')


def summary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Tonnes per kind (hot, cold), road type, vehicle class and component.

    Args:
        tables: kind -> result table (g/km per link piece with length_km and road_type)

    Returns:
        pd.DataFrame: kind, road_type, vehicle_class, component, emission_t
    """
    rows = []
    for kind, table in tables.items():
        columns = emission_columns(table)
        grams = table[columns].mul(table['length_km'], axis=0)
        by_road = grams.groupby(table['road_type']).sum()
        long = by_road.stack().reset_index()
        long.columns = ['road_type', 'column', 'emission_g']
        long[['vehicle_class', 'component']] = long['column'].str.split('_', n=1, expand=True)
        long['emission_t'] = long['emission_g'] / 1e6
        rows.append(long.assign(kind=kind)[['kind', 'road_type', 'vehicle_class', 'component', 'emission_t']])
    return pd.concat(rows, ignore_index=True)
