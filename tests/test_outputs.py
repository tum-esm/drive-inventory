"""Known-answer test of the output summary. All numbers are invented."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pandera.errors import SchemaError
from shapely.geometry import LineString

from drive.outputs import summary, vkt, write_line_sources


def test_summary_converts_g_per_km_and_length_to_tonnes_per_road_type():
    """Two links of 0.5 km and 2 km with 1e6 and 4e6 g/km PC NOx.

    Distributor: 1e6 g/km x 0.5 km = 0.5 t; Motorway: 4e6 g/km x 2 km = 8 t.
    Catches a lost length, g instead of t, and class and component swapped when the column name is split.
    """
    table = pd.DataFrame({'road_link_id': [1, 2], 'from_node': [10, 20], 'piece': [0, 0],
                          'road_type': ['Distributor/Secondary', 'Motorway-Nat'],
                          'scaling_road_type': ['Distributor/Secondary', 'Motorway-Nat'],
                          'length_km': [0.5, 2.0], 'PC_NOx': [1e6, 4e6], 'PC_CO2(rep)': [0.0, 0.0]})

    result = summary({'hot': table}).set_index(['kind', 'road_type', 'vehicle_class', 'component'])['emission_t']

    assert result[('hot', 'Distributor/Secondary', 'PC', 'NOx')] == pytest.approx(0.5)
    assert result[('hot', 'Motorway-Nat', 'PC', 'NOx')] == pytest.approx(8.0)
    assert result.sum() == pytest.approx(8.5)


def test_line_source_contract_rejects_wrong_crs_and_negative_hot_values(tmp_path):
    """Line sources in EPSG:4326 (lengths in degrees) or with a negative hot value must not be written (R7)."""
    def layer(value, crs):
        return gpd.GeoDataFrame({'road_link_id': [1], 'from_node': [10], 'piece': [0],
                                 'road_type': ['Distributor/Secondary'], 'scaling_road_type': ['Distributor/Secondary'],
                                 'length_km': [1.0], 'PC_NOx': [value]},
                                geometry=[LineString([(0, 0), (1000, 0)])], crs=crs)

    write_line_sources(tmp_path / 'ok.gpkg', {'hot': layer(5.0, 'EPSG:25832'), 'cold': layer(-1.0, 'EPSG:25832')})
    with pytest.raises(ValueError, match='EPSG:25832'):
        write_line_sources(tmp_path / 'crs.gpkg', {'hot': layer(5.0, 'EPSG:4326')})
    with pytest.raises(SchemaError):
        write_line_sources(tmp_path / 'neg.gpkg', {'hot': layer(-1.0, 'EPSG:25832')})


def test_vkt_is_volume_times_length_per_road_type_level_of_service_and_class():
    """Two link pieces of the same road type, 0.5 km and 2 km, two classes and two levels of service.

    Piece 1: 1000 PC in Freeflow, 100 HGV in Heavy; piece 2: 500 PC in Freeflow.
    PC Freeflow = 1000 x 0.5 + 500 x 2 = 1500 vehicle-km, HGV Heavy = 50.
    Catches a lost length and volume put on the wrong level of service or class.
    """
    volume = np.zeros((2, 2, 2))  # piece, level of service, class
    volume[0, 0, 0], volume[0, 1, 1], volume[1, 0, 0] = 1000, 100, 500
    road = pd.Series(['Distributor/Secondary'] * 2)

    result = vkt(road, np.array([0.5, 2.0]), volume, ['PC', 'HGV'], ['Freeflow', 'Heavy']) \
        .set_index(['level_of_service', 'vehicle_class'])['vkt_km']

    assert result[('Freeflow', 'PC')] == pytest.approx(1500.0)
    assert result[('Heavy', 'HGV')] == pytest.approx(50.0)
    assert result.sum() == pytest.approx(1550.0)
