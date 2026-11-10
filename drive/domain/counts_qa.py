"""Quality control of traffic counts per road link (port of v1 data_preprocessing/31).

Steps: aggregate detectors per link, add road and day types, check hourly vs daily
consistency, remove outliers, validate against the traffic model (SQV) and flag
completeness in the reference window.

Behaviour kept from v1 for comparability (candidates for later method decisions):
- missing detector values on a link-day are summed as 0
- outliers are detected per (link, vehicle class, day type group) over all years at once
Deliberate change: links without data in the completeness window are incomplete (R3),
v1 marked them complete.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from drive.domain.calendar import group_day_types
from drive.schemas import HOURS, LINK_COUNTS

KEY = ['road_link_id', 'vehicle_class', 'date']


@dataclass
class QAParams:
    reference_year: int
    reference_day_type: int
    completeness_window: tuple[str, str]
    hourly_daily_tolerance: float = 0.025
    min_daily_value: float = 1.0
    outlier_z_threshold: float = 3.5
    sqv_f: float = 10000.0
    sqv_threshold: float = 0.6
    completeness_threshold: float = 0.6
    iqr_range: tuple[float, float] = (2.5, 97.5)
    scaling_road_types: dict[str, str] = field(default_factory=dict)
    outlier_groups: Mapping[int, int] | None = None  # outlier groups, None keeps every day type on its own (v1)


@dataclass
class QAReport:
    rows: dict[str, int] = field(default_factory=dict)  # rows after each step
    outliers: int = 0
    links: int = 0
    links_valid: int = 0
    links_complete: int = 0
    links_without_window_data: list[int] = field(default_factory=list)  # R3: incomplete in v2, complete in v1


def iqr_mean(values: np.ndarray, iqr_range: tuple[float, float] = (2.5, 97.5)) -> float:
    """Mean of the values between two percentiles (inclusive)."""
    values = np.asarray(values)
    lower, upper = np.percentile(values, iqr_range[0]), np.percentile(values, iqr_range[1])
    return float(np.mean(values[(values >= lower) & (values <= upper)]))


def sqv(observed: np.ndarray, model: np.ndarray, f: float = 10000.0) -> np.ndarray:
    """Scalable quality value; f = 10000 is the recommended factor for daily volumes."""
    return 1 / (1 + np.sqrt((model - observed) ** 2 / (f * observed)))


def link_attributes(links: pd.DataFrame) -> pd.DataFrame:
    """Road type and DTV per road_link_id, from LINKS rows (usually one row per direction).

    DTVs are summed per id. If the rows of an id disagree on the road type, the last row wins
    (as in v1) and the id is flagged in `road_type_ambiguous`.

    Returns:
        pd.DataFrame: indexed by road_link_id with road_type, road_type_ambiguous, dtv_*
    """
    grouped = links.groupby('road_link_id')
    attributes = grouped[['dtv_SUM', 'dtv_PC', 'dtv_LCV', 'dtv_HGV']].sum()
    attributes.insert(0, 'road_type', grouped['road_type'].last())
    attributes.insert(1, 'road_type_ambiguous', grouped['road_type'].nunique() > 1)
    return attributes


def link_volumes(raw_counts: pd.DataFrame,
                 counter_links: pd.DataFrame,
                 link_attributes: pd.DataFrame,
                 day_types: pd.Series) -> pd.DataFrame:
    """Daily volumes per road link with road and day type.

    Args:
        raw_counts: RAW_COUNTS rows
        counter_links: COUNTER_LINKS rows of one traffic model
        link_attributes: link_attributes() of the same model
        day_types: day type per date, must cover all dates

    Returns:
        pd.DataFrame: road_link_id, vehicle_class, date, road_type, day_type, daily_value, h00..h23
    """
    volume = raw_counts[raw_counts['metric'] == 'volume']
    volume = volume.merge(counter_links[['source', 'detector_id', 'road_link_id']],
                          on=['source', 'detector_id'], how='inner')
    # detectors of one link (lanes, directions) are summed; NaN counts as 0 as in v1
    volume = volume.groupby(KEY)[['daily_value'] + HOURS].sum().reset_index()

    volume = volume.merge(link_attributes[['road_type', 'road_type_ambiguous']],
                          left_on='road_link_id', right_index=True, how='inner')
    ambiguous = volume.loc[volume['road_type_ambiguous'], 'road_link_id'].unique()
    if len(ambiguous) > 0:
        raise ValueError(f'Counted links with more than one road type in the model: {sorted(ambiguous)}')
    volume = volume[volume['road_type'] != 'none']

    missing_dates = set(volume['date'].unique()) - set(day_types.index)
    if missing_dates:
        raise ValueError(f'No day type for {len(missing_dates)} dates, e.g. {sorted(missing_dates)[:3]}')
    volume['day_type'] = volume['date'].map(day_types).astype('int64')

    return volume[KEY + ['road_type', 'day_type', 'daily_value'] + HOURS].reset_index(drop=True)


def _drop_outliers(volume: pd.DataFrame,
                   threshold: float,
                   outlier_groups: Mapping[int, int] | None = None) -> tuple[pd.DataFrame, int]:
    """Modified z-score per (link, vehicle class, day type group); a group with MAD 0 flags every
    value that differs from the median, as in v1."""
    keys = [volume['road_link_id'], volume['vehicle_class'], group_day_types(volume['day_type'], outlier_groups)]
    deviation = volume['daily_value'] - volume['daily_value'].groupby(keys).transform('median')
    mad = deviation.abs().groupby(keys).transform('median')
    with np.errstate(divide='ignore', invalid='ignore'):
        z = np.abs(0.6745 * deviation / mad)
    outlier = z > threshold
    return volume[~outlier], int(outlier.sum())


def qa_link_counts(volume: pd.DataFrame,
                   link_attributes: pd.DataFrame,
                   params: QAParams) -> tuple[pd.DataFrame, QAReport]:
    """Filters link volumes and adds validity and completeness flags.

    Args:
        volume: output of link_volumes
        link_attributes: link_attributes() (DTVs for the SQV)
        params: thresholds and reference settings

    Returns:
        LINK_COUNTS rows and a report
    """
    report = QAReport()
    report.rows['link_volumes'] = len(volume)

    # hourly values must add up to the daily value
    hourly_sum = volume[HOURS].sum(axis=1)
    e = params.hourly_daily_tolerance
    consistent = hourly_sum.between(volume['daily_value'] * (1 - e), volume['daily_value'] * (1 + e))
    volume = volume[consistent & (volume['daily_value'] > params.min_daily_value)]
    report.rows['consistent'] = len(volume)

    volume, report.outliers = _drop_outliers(volume, params.outlier_z_threshold, params.outlier_groups)
    report.rows['without_outliers'] = len(volume)
    volume = volume.copy()

    # validity: SQV of the reference-year normweekday mean against the model DTV
    reference = volume[(volume['date'].dt.year == params.reference_year) &
                       (volume['day_type'] == params.reference_day_type)]
    observed = reference.groupby(['road_link_id', 'vehicle_class'])['daily_value'] \
        .apply(iqr_mean, iqr_range=params.iqr_range).unstack('vehicle_class')
    dtv = link_attributes.loc[observed.index]
    sqv_per_class = pd.DataFrame({vc: sqv(observed[vc], dtv[f'dtv_{vc}'], params.sqv_f)
                                  for vc in ['SUM', 'PC', 'LCV', 'HGV'] if vc in observed})
    volume['sqv'] = 0.0  # v1 leaves MOT and BUS at 0
    for vc, values in sqv_per_class.items():
        rows = volume['vehicle_class'] == vc
        volume.loc[rows, 'sqv'] = volume.loc[rows, 'road_link_id'].map(values)
    valid_links = sqv_per_class.index[sqv_per_class['SUM'] > params.sqv_threshold]
    volume['valid'] = volume['road_link_id'].isin(valid_links)

    # completeness: SUM days in the window relative to the best covered link
    start, end = params.completeness_window
    window = volume[(volume['vehicle_class'] == 'SUM') & volume['date'].between(start, end)]
    days = window.groupby('road_link_id')['daily_value'].count()
    completeness = days / days.max()
    volume['completeness'] = volume['road_link_id'].map(completeness).fillna(0.0)
    volume['complete'] = volume['completeness'] > params.completeness_threshold  # R3: 0 is incomplete

    volume['scaling_road_type'] = volume['road_type'].map(lambda rt: params.scaling_road_types.get(str(rt), rt))

    links = volume.groupby('road_link_id')[['valid', 'complete', 'completeness']].first()
    report.links = len(links)
    report.links_valid = int(links['valid'].sum())
    report.links_complete = int(links['complete'].sum())
    report.links_without_window_data = sorted(links.index[links['completeness'] == 0].tolist())

    columns = list(LINK_COUNTS.columns)
    return LINK_COUNTS.validate(volume[columns].reset_index(drop=True)), report
