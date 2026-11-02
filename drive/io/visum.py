"""Readers for preprocessed VISUM exports (visum_links_<year>.gpkg)."""

from pathlib import Path

import pyogrio


def read_link_ids(links_path: str | Path) -> set[int]:
    """Set of road_link_ids in a VISUM links file (several rows per id are possible)."""
    links = pyogrio.read_dataframe(links_path, columns=['road_link_id'], read_geometry=False)
    if links['road_link_id'].isna().any():
        raise ValueError(f'{links_path} has links without road_link_id')
    return set(links['road_link_id'].astype('int64'))
