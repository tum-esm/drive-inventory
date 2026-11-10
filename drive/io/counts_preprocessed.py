"""Interim adapter for the preprocessed counting data of v1 (data_preprocessing/11 and 12).

Files: BAST_/MST_TrafficCounts_preprocessed*.parquet with columns
`date, road_link_id, detector_id, detector_type, vehicle_class, metric, daily_value, 0..23`.
The road_link_id comes from the manual QGIS matching. Link ids are stable across the
VISUM models, so one matching is written per traffic model for the links that exist in it.

Replaced by adapters for the raw exports (R16) later.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from drive.schemas import COUNTER_LINKS, HOURS, RAW_COUNTS

_SOURCE_HOURS = [str(h) for h in range(24)]


@dataclass
class CountsIngestReport:
    rows: int = 0
    detectors: int = 0
    detectors_without_link: int = 0
    missing_marker_rows: int = 0
    links_missing_in_model: dict[str, list[int]] = field(default_factory=dict)


def read_preprocessed_counts(path: str | Path,
                             source: str,
                             model_link_ids: dict[str, set[int]]) -> tuple[pd.DataFrame, pd.DataFrame, CountsIngestReport]:
    """Reads one preprocessed counting data file.

    Args:
        path: parquet file
        source: 'BASt' or 'LHM'
        model_link_ids: traffic model -> road_link_ids of that model

    Returns:
        raw counts (RAW_COUNTS), counter links (COUNTER_LINKS) and a report
    """
    df = pd.read_parquet(path)
    report = CountsIngestReport(rows=len(df), detectors=df['detector_id'].nunique())

    # BASt marks missing hours with -1 (daily value = sum of the markers, e.g. -24)
    negative_hours = (df[_SOURCE_HOURS] < 0).any(axis=1)
    missing = negative_hours | (df['daily_value'] < 0)
    report.missing_marker_rows = int(missing.sum())
    hours = df[_SOURCE_HOURS].mask(df[_SOURCE_HOURS] < 0)
    daily = df['daily_value'].mask(missing)

    counts = pd.DataFrame({
        'source': source,
        'detector_id': df['detector_id'].astype(str),
        'detector_type': df['detector_type'],
        'date': df['date'].astype('datetime64[us]'),
        'vehicle_class': df['vehicle_class'],
        'metric': df['metric'],
        'daily_value': daily,
        **dict(zip(HOURS, (hours[h] for h in _SOURCE_HOURS))),
    })
    counts = RAW_COUNTS.validate(counts)

    pairs = df[['detector_id', 'road_link_id']].drop_duplicates()
    if pairs['detector_id'].duplicated().any():
        multi = pairs.loc[pairs['detector_id'].duplicated(keep=False), 'detector_id'].unique()
        raise ValueError(f'{path}: detectors matched to more than one link: {sorted(multi)[:10]}')
    report.detectors_without_link = int(pairs['road_link_id'].isna().sum())
    pairs = pairs.dropna(subset=['road_link_id'])
    pairs = pairs.assign(detector_id=pairs['detector_id'].astype(str),
                         road_link_id=pairs['road_link_id'].astype('int64'))

    links = []
    for model, link_ids in sorted(model_link_ids.items()):
        exists = pairs['road_link_id'].isin(link_ids)
        report.links_missing_in_model[model] = sorted(pairs.loc[~exists, 'road_link_id'].unique().tolist())
        links.append(pairs[exists].assign(source=source, traffic_model=model))
    links = COUNTER_LINKS.validate(
        pd.concat(links)[['source', 'detector_id', 'traffic_model', 'road_link_id']].reset_index(drop=True))

    return counts, links, report
