"""Cold start excess emissions: vehicle starts per link (port of v1 notebook 11). No IO.

The traffic model gives daily vehicle starts per zone. Each zone's starts go to the links of the
included road types within a buffer around the zone, weighted by the links' share of the total
volume (dtv_SUM) of those links. Motorways and primary city roads are assumed to carry hot traffic
only, so they are left out. A link near several zones collects starts from each.
"""

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd


@dataclass
class StartsReport:
    zones: int
    zones_without_links: list[int]  # zone_id of zones with no included link in their buffer; their starts are lost
    lost_starts: dict[str, float]  # vehicle class -> daily starts of those zones


def distribute_starts(links: gpd.GeoDataFrame,
                      zones: gpd.GeoDataFrame,
                      vehicle_classes: list[str],
                      road_types: list[str],
                      buffer_m: float) -> tuple[pd.DataFrame, StartsReport]:
    """Daily vehicle starts per link.

    Args:
        links: LINKS rows with geometry (road_type, dtv_SUM)
        zones: ZONES rows with geometry and a `{class}_starts` column per vehicle class
        buffer_m: buffer around each zone, in units of the CRS (v1: 1500 m)

    Returns:
        one `{class}_starts` column per vehicle class, on the index of `links`, and a report

    Raises:
        ValueError: if the CRSs differ or a zone lacks starts of a vehicle class
    """
    if links.crs != zones.crs or links.crs is None:
        raise ValueError(f'links and zones need the same CRS, got {links.crs} and {zones.crs}')
    columns = [f'{c}_starts' for c in vehicle_classes]
    missing = [c for c in columns if c not in zones.columns or zones[c].isna().any()]
    if missing:
        raise ValueError(f'The zones lack {missing}')

    eligible = links.loc[links['road_type'].isin(road_types), ['dtv_SUM', 'geometry']]
    buffers = gpd.GeoDataFrame(zones[columns].reset_index(drop=True), geometry=zones.geometry.buffer(buffer_m).values,
                               crs=zones.crs)
    pairs = gpd.sjoin(buffers, eligible, how='inner', predicate='intersects')  # index: zone row, index_right: link
    zone_row = pairs.index.to_numpy()
    share = pairs['dtv_SUM'] / pairs.groupby(level=0)['dtv_SUM'].transform('sum')

    starts = pd.DataFrame(0.0, index=links.index, columns=columns)
    for c in columns:
        per_link = (share * pairs[c]).groupby(pairs['index_right'].to_numpy()).sum()
        starts.loc[per_link.index, c] = per_link.to_numpy()

    empty = np.setdiff1d(np.arange(len(zones)), zone_row)
    report = StartsReport(zones=len(zones),
                          zones_without_links=zones['zone_id'].iloc[empty].tolist() if 'zone_id' in zones else
                          empty.tolist(),
                          lost_starts={c: float(zones[f'{c}_starts'].iloc[empty].sum()) for c in vehicle_classes})
    return starts, report
