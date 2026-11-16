"""Known-answer test of the counter link overrides (R26). All ids are invented."""

import pandas as pd
import pytest

from drive.io.counter_links import apply_overrides


def test_overrides_move_exclude_and_respect_the_traffic_model():
    """Detector A moves to link 20 in every model, B is excluded only in visum2025, C stays.

    Catches an override that is silently not applied, applied to the wrong model, or that points to a
    link the model doesn't have.
    """
    links = pd.DataFrame({'source': 'BASt', 'detector_id': ['A', 'B', 'C'], 'traffic_model': 'visum2025',
                          'road_link_id': [10, 11, 12]})
    overrides = pd.DataFrame({'source': 'BASt', 'detector_id': ['A', 'B', 'B'],
                              'traffic_model': ['', 'visum2025', 'visum2019'], 'road_link_id': ['20', '', '30'],
                              'reason': ['moved', 'faulty', 'other model']})

    result, applied = apply_overrides(links, overrides, 'visum2025', model_link_ids={10, 11, 12, 20})

    assert dict(zip(result['detector_id'], result['road_link_id'])) == {'A': 20, 'C': 12}
    assert len(applied) == 2
    with pytest.raises(ValueError, match='not in visum2025'):
        apply_overrides(links, overrides, 'visum2025', model_link_ids={10, 11, 12})
