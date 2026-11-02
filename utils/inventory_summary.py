"""Module to summarise inventory outputs into small tables, so that runs
(e.g. before and after a bug fix) can be compared against a stored baseline.
"""

__version__ = 0.1
__author__ = "Daniel Kühbacher"

import pandas as pd
import geopandas as gpd

VEHICLE_CLASSES = ['PC', 'LCV', 'HGV', 'MOT', 'BUS']


def summarise_lines(gpkg_path: str,
                    by: list[str] | None = None) -> pd.DataFrame:
    """Annual emissions of a line source file per vehicle class and component.

    Line source GeoPackages (hot linesource_*.gpkg and cold csee_*.gpkg) store
    emissions per link in g/km in columns named '<vehicle class>_<component>'.
    The total is the sum over links of (g/km x link length in km). Other columns
    (link attributes) are ignored unless used in `by`.

    Args:
        gpkg_path (str): path to a line source file
        by (list[str], optional): link attributes to group by, e.g. ['road_type']

    Returns:
        pd.DataFrame: columns *by, vehicle_class, component, total_g
    """
    by = by or []
    links = gpd.read_file(gpkg_path)
    if links.crs is None or not links.crs.is_projected:
        raise ValueError(f'{gpkg_path} needs a projected (metric) CRS, got {links.crs}')

    emission_cols = [c for c in links.columns
                     if c.partition('_')[0] in VEHICLE_CLASSES and c.partition('_')[2]]
    if not emission_cols:
        raise ValueError(f'No <vehicle class>_<component> columns in {gpkg_path}')

    length_km = links.geometry.length * 1e-3
    totals = links[emission_cols].mul(length_km, axis=0)
    totals[by] = links[by]
    totals = (totals.groupby(by).sum() if by else totals.sum().to_frame().T)
    totals = totals.melt(ignore_index=False, var_name='column', value_name='total_g')
    totals = totals.reset_index(drop=not by)
    split = totals['column'].str.split('_', n=1, expand=True)
    totals['vehicle_class'], totals['component'] = split[0], split[1]
    return totals[by + ['vehicle_class', 'component', 'total_g']]


def summarise_profile(csv_path: str) -> pd.DataFrame:
    """Monthly mean scaling factor per component of a temporal profile.

    Args:
        csv_path (str): path to a temporal profile csv (year, component, timestamp, scaling_factor)

    Returns:
        pd.DataFrame: columns component, month, mean_scaling_factor
    """
    profile = pd.read_csv(csv_path, parse_dates=['timestamp'])
    profile['month'] = profile['timestamp'].dt.month
    return (profile.groupby(['component', 'month'])['scaling_factor']
            .mean()
            .rename('mean_scaling_factor')
            .reset_index())


def compare(before: pd.DataFrame,
            after: pd.DataFrame,
            value: str) -> pd.DataFrame:
    """Absolute and relative difference between two summaries.

    Args:
        before (pd.DataFrame): summary of the reference run
        after (pd.DataFrame): summary of the new run, same key columns
        value (str): name of the value column, e.g. 'total_g'

    Returns:
        pd.DataFrame: key columns, before, after, abs_diff, rel_diff
    """
    keys = [c for c in before.columns if c != value]
    merged = before.merge(after, on=keys, how='outer',
                          suffixes=('_before', '_after'), indicator=True)
    if (merged['_merge'] != 'both').any():
        missing = merged.loc[merged['_merge'] != 'both', keys + ['_merge']]
        raise ValueError(f'Summaries have different keys:\n{missing}')

    merged = merged.drop(columns='_merge').rename(
        columns={f'{value}_before': 'before', f'{value}_after': 'after'})
    merged['abs_diff'] = merged['after'] - merged['before']
    merged['rel_diff'] = merged['abs_diff'] / merged['before'].abs()
    return merged
