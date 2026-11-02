"""Readers for preprocessed VISUM exports (visum_links_<year>.gpkg)."""

from pathlib import Path

import pandas as pd
import pyogrio

_DTV_COLUMNS = ['dtv_SUM', 'dtv_PC', 'dtv_LCV', 'dtv_HGV']


def read_link_attributes(links_path: str | Path) -> pd.DataFrame:
    """Road type and DTV per road_link_id (a link id can have several rows, e.g. per direction).

    DTVs are summed per link. If the rows of a link disagree on the road type, the last
    row wins (as in v1) and the link is flagged in `road_type_ambiguous`.

    Returns:
        pd.DataFrame: indexed by road_link_id with road_type, road_type_ambiguous, dtv_*
    """
    links = pyogrio.read_dataframe(links_path, columns=['road_link_id', 'road_type'] + _DTV_COLUMNS,
                                   read_geometry=False)
    links['road_link_id'] = links['road_link_id'].astype('int64')
    grouped = links.groupby('road_link_id')
    attributes = grouped[_DTV_COLUMNS].sum()
    attributes.insert(0, 'road_type', grouped['road_type'].last())
    attributes.insert(1, 'road_type_ambiguous', grouped['road_type'].nunique() > 1)
    return attributes


def read_link_ids(links_path: str | Path) -> set[int]:
    """Set of road_link_ids in a VISUM links file (several rows per id are possible)."""
    links = pyogrio.read_dataframe(links_path, columns=['road_link_id'], read_geometry=False)
    if links['road_link_id'].isna().any():
        raise ValueError(f'{links_path} has links without road_link_id')
    return set(links['road_link_id'].astype('int64'))
