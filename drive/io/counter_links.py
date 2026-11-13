"""Detector -> road link matchings per traffic model (manual QGIS matching today, R26).

Link ids are stable across the VISUM models, so one matching is written per traffic model for the
links that exist in it.
"""

import pandas as pd

from drive.schemas import COUNTER_LINKS


def links_per_model(pairs: pd.DataFrame,
                    source: str,
                    model_link_ids: dict[str, set[int]]) -> tuple[pd.DataFrame, dict[str, list[int]]]:
    """COUNTER_LINKS rows for every traffic model.

    Args:
        pairs: detector_id, road_link_id (one link per detector, links without NaN)
        model_link_ids: traffic model -> road_link_ids of that model

    Returns:
        counter links, and per model the matched links that are not in it

    Raises:
        ValueError: if a detector is matched to more than one link
    """
    pairs = pairs[['detector_id', 'road_link_id']].drop_duplicates()
    multi = pairs.loc[pairs['detector_id'].duplicated(keep=False), 'detector_id'].unique()
    if len(multi) > 0:
        raise ValueError(f'{source}: detectors matched to more than one link: {sorted(multi)[:10]}')
    pairs = pairs.assign(detector_id=pairs['detector_id'].astype(str), road_link_id=pairs['road_link_id'].astype('int64'))

    links, missing = [], {}
    for model, link_ids in sorted(model_link_ids.items()):
        exists = pairs['road_link_id'].isin(link_ids)
        missing[model] = sorted(pairs.loc[~exists, 'road_link_id'].unique().tolist())
        links.append(pairs[exists].assign(source=source, traffic_model=model))
    frame = pd.concat(links)[['source', 'detector_id', 'traffic_model', 'road_link_id']].reset_index(drop=True)
    return COUNTER_LINKS.validate(frame), missing
