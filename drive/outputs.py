"""Output products of a run (spec R12): line-source GeoPackage, summary table and gridded emissions.

Units: the line sources hold g/km per link piece over the run's period (one year), as v1's
`linesource_*.gpkg`; the summary holds tonnes per period. Totals of a component are the sum of
g/km x length over the link pieces, so the line sources and the summary add up to the same numbers.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

from drive.domain.gridding import by_component, grid_line_sources

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


def gridded(layers: dict[str, gpd.GeoDataFrame], grid: gpd.GeoDataFrame, cell_id: str) -> dict[str, gpd.GeoDataFrame]:
    """Emissions per grid cell and component in kg over the period: one layer per kind plus `total`.

    Every cell of the grid is kept, zeros included. The cells are returned in the CRS of the line sources.
    """
    crs = next(iter(layers.values())).crs
    if crs is None:
        raise ValueError('The line sources have no CRS')
    cells = grid[[cell_id, 'geometry']].to_crs(crs)
    result = {}
    for kind, lines in layers.items():
        per_class = grid_line_sources(lines, emission_columns(lines), grid, cell_id)
        result[kind] = by_component(per_class) / 1000
    result['total'] = _total(list(result.values()))
    return {kind: gpd.GeoDataFrame(cells.set_index(cell_id).join(frame).reset_index(), geometry='geometry',
                                   crs=cells.crs) for kind, frame in result.items()}


def _total(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Cell-wise sum over kinds; a component missing in a kind counts as 0."""
    total = frames[0]
    for frame in frames[1:]:
        total = total.add(frame, fill_value=0.0)
    return total
