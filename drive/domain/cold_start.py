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


# HBEFA start factors exist for these ambient temperatures (°C); trip duration and length are averages
TEMPERATURE_BINS = np.array([-10, -5, 0, 5, 10, 15, 20, 25])


def start_patterns(temperature: np.ndarray) -> np.ndarray:
    """HBEFA ambient pattern of each temperature: the nearest bin, ties to the lower bin (v1).

    Raises:
        ValueError: on NaN or infinite temperatures, which v1 once turned into -10 °C silently
    """
    temperature = np.asarray(temperature, dtype=float)
    if not np.isfinite(temperature).all():
        raise ValueError(f'{(~np.isfinite(temperature)).sum()} invalid temperatures')
    nearest = TEMPERATURE_BINS[np.abs(temperature[:, None] - TEMPERATURE_BINS[None, :]).argmin(axis=1)]
    return np.array([f'T{b:+d}°C,tØ,dØ' for b in nearest])


def hourly_cold_emissions(temperature: pd.Series,
                          hourly_starts: pd.DataFrame,
                          factors: pd.DataFrame,
                          components: list[str]) -> pd.DataFrame:
    """Cold start excess emissions per hour, vehicle class and component (g).

    Args:
        temperature: ambient temperature per hour (°C)
        hourly_starts: starts per hour (same index), one column per vehicle class
        factors: EMISSION_FACTORS rows of a start table (g/start)

    Returns:
        long table: time, vehicle_class, component, emission_g

    Raises:
        ValueError: if the indexes differ or a factor is missing
    """
    if not temperature.index.equals(hourly_starts.index):
        raise ValueError('temperature and hourly_starts need the same index')
    patterns = start_patterns(temperature.to_numpy())
    frames = []
    for vc in hourly_starts.columns:
        table = factors[factors['vehicle_class'] == vc].pivot(index='ambient_pattern', columns='pollutant', values='efa')
        table = table.reindex(index=np.unique(patterns), columns=components)
        if table.isna().any().any():
            isna = table.isna().to_numpy()
            missing = [(p, c) for i, p in enumerate(table.index) for j, c in enumerate(table.columns) if isna[i, j]]
            raise ValueError(f'No {vc} start factors for {missing[:5]}')
        ef = table.loc[patterns].to_numpy()  # hour x component, g/start
        emission = ef * hourly_starts[vc].to_numpy()[:, None]
        frames.append(pd.DataFrame({
            'time': np.repeat(temperature.index.to_numpy(), len(components)),
            'vehicle_class': vc,
            'component': np.tile(components, len(temperature)),
            'emission_g': emission.ravel(),
        }))
    return pd.concat(frames, ignore_index=True)


def link_cold_emissions(weights: pd.DataFrame, totals: pd.Series) -> pd.DataFrame:
    """Distributes the period's totals to links in proportion to their starts.

    Args:
        weights: starts per link, one column per vehicle class
        totals: g per (vehicle_class, component)

    Returns:
        g per link, columns `{vehicle_class}_{component}`
    """
    share = weights / weights.sum()
    columns = {f'{vc}_{c}': share[vc] * totals[(vc, c)] for vc, c in totals.index}
    return pd.DataFrame(columns, index=weights.index)
