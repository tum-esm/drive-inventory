"""Gridding of line sources (spec R12b, port of v1 utils/gridding.GriddingEngine.overlay_grid). No IO.

Every line is cut at the cell borders; the part inside a cell carries g/km x its length. v1 cut the
lines with an overlay and assigned each part to the cell containing its centroid; here the length
inside each intersecting cell is computed directly, which gives the same result without the
centroid step.
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


def grid_line_sources(lines: gpd.GeoDataFrame, columns: list[str], grid: gpd.GeoDataFrame,
                      cell_id: str) -> pd.DataFrame:
    """Emissions per grid cell from line sources in g/km.

    Args:
        lines: line sources with the value columns in g/km, in a metric CRS
        columns: the value columns
        grid: cells with `cell_id`, in any CRS (reprojected to the lines' CRS)
        cell_id: the cell id column of `grid`

    Returns:
        pd.DataFrame indexed by cell id (every cell of the grid, zeros included), one column per value
        column in g over the period of the line sources
    """
    if lines.crs is None or not lines.crs.is_projected:
        raise ValueError('The line sources need a projected CRS in metres')
    cells = grid.to_crs(lines.crs)
    line_index, cell_index = cells.sindex.query(lines.geometry, predicate='intersects')
    pieces = shapely.intersection(lines.geometry.to_numpy()[line_index], cells.geometry.to_numpy()[cell_index])
    length_km = shapely.length(pieces) / 1000
    values = lines[columns].to_numpy(dtype=float)[line_index] * length_km[:, None]
    totals = np.zeros((len(cells), len(columns)))
    np.add.at(totals, cell_index, values)
    return pd.DataFrame(totals, index=pd.Index(cells[cell_id].to_numpy(), name=cell_id), columns=columns)


def by_component(gridded: pd.DataFrame) -> pd.DataFrame:
    """Sum of the {vehicle_class}_{component} columns per component."""
    components = gridded.columns.str.split('_', n=1).str[1]
    return gridded.T.groupby(components.to_numpy()).sum().T
