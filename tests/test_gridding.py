"""Known-answer test of the gridding. All numbers are invented."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from drive.domain.gridding import by_component, grid_line_sources


def test_a_line_is_split_between_cells_by_its_length_inside_each():
    """Two 1 km cells side by side; a 1.5 km line from x = 0.25 km to 1.75 km, 1000 g/km PC NOx and 400 g/km HGV NOx.

    Cell A gets 0.75 km x 1000 = 750 g PC, cell B the same; HGV 300 g each; NOx per cell 1050 g.
    Catches lengths in m instead of km, a line counted whole in every cell it touches, and a wrong cell order.
    """
    grid = gpd.GeoDataFrame({'locationcode': ['A', 'B'], 'geometry': [box(0, 0, 1000, 1000), box(1000, 0, 2000, 1000)]},
                            crs='EPSG:25832')
    lines = gpd.GeoDataFrame({'PC_NOx': [1000.0], 'HGV_NOx': [400.0]},
                             geometry=[LineString([(250, 500), (1750, 500)])], crs='EPSG:25832')

    cells = grid_line_sources(lines, ['PC_NOx', 'HGV_NOx'], grid, 'locationcode')

    assert cells.loc['A', 'PC_NOx'] == pytest.approx(750.0)
    assert cells.loc['B', 'HGV_NOx'] == pytest.approx(300.0)
    assert by_component(cells)['NOx'].to_dict() == pytest.approx({'A': 1050.0, 'B': 1050.0})
    assert list(cells.index) == ['A', 'B'] and isinstance(cells, pd.DataFrame)
