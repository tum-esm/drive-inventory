"""Quality control of traffic counts per road link (port of v1 data_preprocessing/31).

Steps: aggregate detectors per link, add road and day types, check hourly vs daily
consistency, remove outliers, remove implausible class shares, validate against the traffic
model (SQV) and flag completeness per year.

A counter (link) is used for year Y only if it is valid and complete for Y (spec R46, D29):
- valid: the SQV of its reference-year normal-weekday mean against the model DTV is above
  `sqv_threshold`. A counter that doesn't match the model is more likely wrong or assigned to the
  wrong link than the model is wrong, so it is dropped for every year.
- complete for Y: it has SUM data on at least `completeness_threshold` of the days of the reference
  year and of Y, each year on its own. Without enough reference-year data no unbiased scaling is
  possible.

Behaviour kept from v1 for comparability (candidates for later method decisions):
- outliers are detected per (link, vehicle class, day type group) over all years at once
Deliberate changes: completeness per year as above (R46); v1 had one flag per link from a window,
relative to the best covered link (and R3: links without data in it were complete). Implausible class shares are removed per link and year (R44, not in v1).
Incomplete link-days are dropped (R41, D28): hours with a missing-value flag or without a value, and
days on which a detector of the link didn't report; v1 summed missing values as 0.
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
    hourly_daily_tolerance: float = 0.025
    min_daily_value: float = 1.0
    outlier_z_threshold: float = 3.5
    sqv_f: float = 10000.0
    sqv_threshold: float = 0.6
    completeness_threshold: float = 0.8  # share of the days of a year with SUM data, see the module docstring
    period: tuple[str, str] | None = None  # counts period; a year's days are counted inside it (None: whole years)
    iqr_range: tuple[float, float] = (2.5, 97.5)
    scaling_road_types: dict[str, str] = field(default_factory=dict)
    outlier_groups: Mapping[int, int] | None = None  # outlier groups, None keeps every day type on its own (v1)
    missing_flags: tuple[str, ...] = ()  # hour flags that mean "no value" (BASt: a, d, x); () ignores flags (v1)
    drop_incomplete_days: bool = False  # drop link-days with a missing hour or detector; False sums them as 0 (v1)
    share_check_classes: tuple[str, ...] = ()  # classes checked by _drop_share_outliers; () skips the step (v1)
    share_z_threshold: float = 3.5
    share_min_days: int = 30  # link-years with fewer days with a class split are not checked
    share_min_links: int = 5  # groups with fewer link-years are not checked


@dataclass
class QAReport:
    rows: dict[str, int] = field(default_factory=dict)  # rows after each step
    incomplete_days: int = 0  # link-days (per class) dropped by link_volumes, see drop_incomplete_days
    counter_link_overrides: list[str] = field(default_factory=list)  # applied corrections of the matching (R26)
    outliers: int = 0
    links: int = 0
    links_valid: int = 0
    links_complete_reference: int = 0  # links complete in the reference year
    usable_links: dict[int, int] = field(default_factory=dict)  # year -> links valid and complete for that year
    share_outliers: pd.DataFrame | None = None  # link-years whose class counts were removed, see _drop_share_outliers


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
                 day_types: pd.Series,
                 missing_flags: tuple[str, ...] = (),
                 drop_incomplete_days: bool = False) -> tuple[pd.DataFrame, int]:
    """Daily volumes per road link with road and day type.

    The detectors of a link (lanes, directions) are summed per day and class. With
    `drop_incomplete_days` a link-day of a class is dropped when one of its detectors has an hour
    without a value or with a flag in `missing_flags`, or when a detector that reported on the link
    in that year has no row that day. Otherwise (v1) missing values count as 0, which makes such
    days too low: BASt days with 1-3 missing hours by about 10 %, LHM link-days with a missing lane
    detector by about 22 % (spec R41). BASt's estimates (`s`, `k`) are kept: they show no bias.

    Args:
        raw_counts: RAW_COUNTS rows
        counter_links: COUNTER_LINKS rows of one traffic model
        link_attributes: link_attributes() of the same model
        day_types: day type per date, must cover all dates
        missing_flags: hour flags that mean "no value"
        drop_incomplete_days: see above

    Returns:
        road_link_id, vehicle_class, date, road_type, day_type, daily_value, h00..h23; and the number
        of link-days dropped as incomplete
    """
    volume = raw_counts[raw_counts['metric'] == 'volume']
    volume = volume.merge(counter_links[['source', 'detector_id', 'road_link_id']],
                          on=['source', 'detector_id'], how='inner')
    dropped = 0
    if drop_incomplete_days:
        hours = volume[HOURS].to_numpy(dtype=float)
        missing = np.isnan(hours)
        if missing_flags:
            flags = volume['flags'].fillna('-' * 24).str.pad(24, side='right', fillchar='-')
            flag_hours = flags.to_numpy(dtype='U24').view('U1').reshape(-1, 24)  # one character per hour
            missing |= np.isin(flag_hours, list(missing_flags))
        year = volume['date'].dt.year
        detectors = volume.groupby([volume['road_link_id'], year])['detector_id'].transform('nunique')
        per_day = volume.groupby(KEY)['detector_id'].transform('nunique')
        incomplete = pd.Series(missing.any(axis=1), index=volume.index) | (per_day < detectors)
        incomplete = incomplete.groupby([volume[k] for k in KEY]).transform('any')
        dropped = int(volume.loc[incomplete, KEY].drop_duplicates().shape[0])
        volume = volume[~incomplete]
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

    return volume[KEY + ['road_type', 'day_type', 'daily_value'] + HOURS].reset_index(drop=True), dropped


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


def _days_in_year(year: int, period: tuple[str, str] | None) -> int:
    start, end = pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 31)
    if period is not None:
        start, end = max(start, pd.Timestamp(period[0])), min(end, pd.Timestamp(period[1]))
    return max((end - start).days + 1, 0)


def class_shares(volume: pd.DataFrame, classes: tuple[str, ...], min_days: int = 1) -> pd.DataFrame:
    """Annual share of each class in SUM per link, over the days on which both are counted.

    Returns:
        pd.DataFrame: road_link_id, scaling_road_type, year, vehicle_class, days, share
    """
    daily = volume.pivot_table(index=['road_link_id', 'scaling_road_type', 'date'], columns='vehicle_class',
                               values='daily_value', aggfunc='sum')
    rows = []
    for vehicle_class in classes:
        if vehicle_class not in daily or 'SUM' not in daily:
            continue
        both = daily[['SUM', vehicle_class]].dropna()
        both = both.assign(year=pd.DatetimeIndex(both.index.get_level_values('date')).year)
        annual = both.groupby(['road_link_id', 'scaling_road_type', 'year']) \
            .agg(counted=(vehicle_class, 'sum'), total=('SUM', 'sum'), days=('SUM', 'size'))
        annual = annual[annual['days'] >= min_days]
        rows.append(annual.assign(vehicle_class=vehicle_class, share=annual['counted'] / annual['total']).reset_index())
    columns = ['road_link_id', 'scaling_road_type', 'year', 'vehicle_class', 'days', 'share']
    return pd.concat(rows)[columns] if rows else pd.DataFrame(columns=columns)


def _drop_share_outliers(volume: pd.DataFrame, params: QAParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Removes a class's counts on links whose annual share of that class is implausible (R44).

    Detectors classify vehicles by length and shape, and a faulty or misconfigured detector can count a
    class far off while SUM stays right (e.g. a BASt station with 26 % LCV against about 11 % on the
    other motorways). The annual share of each class in `share_check_classes` is compared with the
    other links of the same scaling road type and year: a robust z-score of the log share (median and
    MAD, as for the daily outliers) above `share_z_threshold` removes that class on the link for the
    year. SUM and the other classes stay. Log shares make a share half and double the median equally
    far off. HGV is not checked by default: its shares differ between links for real (2-25 %).

    Returns:
        volume without the removed rows, and the removed link-years with share, ratio to the median and z
    """
    shares = class_shares(volume, params.share_check_classes, params.share_min_days)
    shares = shares[shares['share'] > 0].copy()
    keys = ['scaling_road_type', 'year', 'vehicle_class']
    log_share = pd.Series(np.log(shares['share'].to_numpy(dtype=float)), index=shares.index)
    median = log_share.groupby([shares[k] for k in keys]).transform('median')
    mad = (log_share - median).abs().groupby([shares[k] for k in keys]).transform('median')
    size = log_share.groupby([shares[k] for k in keys]).transform('size')
    shares['ratio_to_median'] = np.exp((log_share - median).to_numpy())
    shares['z'] = 0.6745 * (log_share - median) / mad
    flagged = shares[(size >= params.share_min_links) & (shares['z'].abs() > params.share_z_threshold)]

    year = volume['date'].dt.year
    drop = pd.MultiIndex.from_frame(flagged[['road_link_id', 'year', 'vehicle_class']])
    rows = pd.MultiIndex.from_arrays([volume['road_link_id'], year, volume['vehicle_class']])
    return volume[~rows.isin(drop)], flagged.reset_index(drop=True)


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
    volume['scaling_road_type'] = volume['road_type'].map(lambda rt: params.scaling_road_types.get(str(rt), rt))

    if params.share_check_classes:
        volume, report.share_outliers = _drop_share_outliers(volume, params)
        report.rows['without_share_outliers'] = len(volume)

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

    # completeness per link and year: SUM days with data over the days of the year (inside the counts period)
    year = volume['date'].dt.year
    totals = volume[volume['vehicle_class'] == 'SUM']
    days = totals.groupby([totals['road_link_id'], totals['date'].dt.year.rename('year')])['date'].nunique()
    days_in_year = pd.Series({y: _days_in_year(y, params.period) for y in days.index.get_level_values('year').unique()})
    denominator = days_in_year.reindex(days.index.get_level_values('year')).to_numpy()
    completeness = (days / denominator).rename('completeness')
    pairs = pd.MultiIndex.from_arrays([volume['road_link_id'], year])
    volume['completeness'] = completeness.reindex(pairs).fillna(0.0).to_numpy()
    reference = completeness.xs(params.reference_year, level='year') if params.reference_year in days_in_year else \
        pd.Series(dtype=float)
    reference_complete = volume['road_link_id'].map(reference).fillna(0.0) >= params.completeness_threshold
    volume['complete'] = reference_complete & (volume['completeness'] >= params.completeness_threshold)

    links = volume.groupby('road_link_id')['valid'].first()
    report.links = len(links)
    report.links_valid = int(links.sum())
    report.links_complete_reference = int((reference >= params.completeness_threshold).sum())
    usable = volume[volume['valid'] & volume['complete']]
    report.usable_links = {int(y): int(n) for y, n in
                           usable.groupby(usable['date'].dt.year)['road_link_id'].nunique().items()}

    columns = list(LINK_COUNTS.columns)
    return LINK_COUNTS.validate(volume[columns].reset_index(drop=True)), report
