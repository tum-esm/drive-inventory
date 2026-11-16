"""Detector -> road link matchings per traffic model (manual QGIS matching, R26).

Link ids are stable across the VISUM models, so one matching is written per traffic model for the
links that exist in it. Corrections of the matching are kept in an override file in git
(`counts_qa.counter_link_overrides`) and applied when a run reads the matching (`apply_overrides`).
"""

from pathlib import Path

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


OVERRIDE_COLUMNS = ['source', 'detector_id', 'traffic_model', 'road_link_id', 'reason']


def read_overrides(path: str | Path) -> pd.DataFrame:
    """The override file: one row per correction.

    Columns: source, detector_id, traffic_model (empty: every model), road_link_id (empty: the detector is
    excluded), reason (required, why the matching is changed).

    Raises:
        ValueError: on missing columns, an empty reason or a detector listed twice for the same model
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, comment='#', skipinitialspace=True)
    missing = set(OVERRIDE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f'{path}: missing columns {sorted(missing)}')
    frame = frame[OVERRIDE_COLUMNS].apply(lambda column: column.str.strip())
    if (frame['reason'] == '').any():
        raise ValueError(f'{path}: every override needs a reason')
    if frame.duplicated(['source', 'detector_id', 'traffic_model']).any():
        raise ValueError(f'{path}: a detector is listed twice for the same traffic model')
    return frame


def apply_overrides(counter_links: pd.DataFrame, overrides: pd.DataFrame, traffic_model: str,
                    model_link_ids: set[int]) -> tuple[pd.DataFrame, list[str]]:
    """The counter links of one traffic model with the overrides applied.

    Args:
        counter_links: COUNTER_LINKS rows of the model
        overrides: read_overrides(); rows of other models are ignored
        model_link_ids: road_link_ids of the model, a new link must be one of them

    Returns:
        the corrected counter links, and one line per applied override

    Raises:
        ValueError: if an override names a detector that has no link in the model, or a link not in the model
    """
    rows = overrides[overrides['traffic_model'].isin(['', traffic_model])]
    links = counter_links.copy()
    applied = []
    for row in rows.itertuples(index=False):
        match = (links['source'] == row.source) & (links['detector_id'] == row.detector_id)
        if not match.any():
            raise ValueError(f'Override for {row.source} {row.detector_id}: no link in {traffic_model}')
        if row.road_link_id == '':
            links = links[~match]
            applied.append(f'{row.source} {row.detector_id} excluded ({row.reason})')
            continue
        new = int(str(row.road_link_id))
        if new not in model_link_ids:
            raise ValueError(f'Override for {row.source} {row.detector_id}: link {new} not in {traffic_model}')
        old = links.loc[match, 'road_link_id'].to_numpy(dtype='int64')[0]
        links.loc[match, 'road_link_id'] = new
        applied.append(f'{row.source} {row.detector_id} {old} -> {new} ({row.reason})')
    links = links.reset_index(drop=True)
    COUNTER_LINKS.validate(links[list(COUNTER_LINKS.columns)])
    return links, applied
