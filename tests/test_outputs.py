"""Known-answer test of the output summary. All numbers are invented."""

import pandas as pd
import pytest

from drive.outputs import summary


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
