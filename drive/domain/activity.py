"""Traffic activity from link counts (port of v1 utils/traffic_counts.TrafficCounts).

Provides per scaling road type and date: the annual cycle (daily scaling relative to the
reference day type of the reference year) and vehicle shares, plus diurnal cycles per
(year, month, day type, vehicle class) and the combined hourly time profile.

Behaviour kept from v1 for comparability (candidates for later method decisions):
- diurnal cycles ignore road type and the complete/valid flags
- annual cycles use complete links, without the valid flag; vehicle shares use complete
  and valid links
In the pipeline these filters no longer matter: `pipeline.load_activity` passes only rows that are
valid and complete for their year (spec R46, D29), so all three use the same counters per year.
The class itself is unchanged, so that it stays identical to v1 on v1's input.
- fill_gaps smooths over 5 consecutive (year, ISO week, day type) rows, so the window mixes
  day types and spans about one week, not 5 weeks
Optional (`share_pools`, spec D30): vehicle classes whose share is computed over several scaling road
types together, e.g. BUS and MOT over the city road types, where few counters see them and bus
volumes depend on the routes. Without pools the shares are those of v1.
Deliberate change: days without data still give zeros in the time profile, but they are
listed in `missing_days` (v1 swallowed the exception).
"""

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from drive.domain.calendar import group_day_types
from drive.domain.counts_qa import iqr_mean
from drive.schemas import HOURS, LINK_VEHICLE_CLASSES

VEHICLE_CLASSES = [vc for vc in LINK_VEHICLE_CLASSES if vc != 'SUM']
_SHARE_LEVELS = ['vehicle_class', 'scaling_road_type', 'date']
_REQUIRED = ['road_link_id', 'vehicle_class', 'date', 'scaling_road_type', 'day_type',
             'valid', 'complete', 'daily_value'] + HOURS


def _fill_category(values: pd.Series, day_types: pd.Series) -> pd.Series:
    """Fills the gaps of one date-indexed series with the smoothed (year, ISO week, day type) mean."""
    dates = pd.DatetimeIndex(values.index)
    keys = pd.MultiIndex.from_arrays(
        [dates.year, dates.isocalendar().week.to_numpy(), day_types.reindex(dates).to_numpy()],
        names=['year', 'week', 'day_type'])
    means = pd.Series(values.to_numpy(), index=keys).groupby(level=keys.names).mean()
    smoothed = means.rolling(window=5, min_periods=1, center=True).mean().bfill()
    return values.fillna(pd.Series(smoothed.reindex(keys).to_numpy(), index=dates))


def fill_gaps(values: pd.Series, day_types: pd.Series) -> pd.Series:
    """Completes a series to all dates and fills its gaps, per category combination.

    Args:
        values: indexed by one or more category levels, with `date` as the last level
        day_types: day type or day type group per date, must cover the whole date range

    Returns:
        pd.Series with the same index levels. All dates between the overall first and last
        date for every category combination that has data; combinations without data are left out.
    """
    categories = list(values.index.names[:-1])
    dates = pd.date_range(values.index.get_level_values('date').min(),
                          values.index.get_level_values('date').max(), name='date')
    filled = {}
    for key, group in values.groupby(level=categories):
        group = group.droplevel(categories).reindex(dates)
        if group.notna().any():
            filled[key] = _fill_category(group, day_types)
    return pd.concat(filled, names=categories).sort_index().rename(values.name)


class Activity:
    """Scaling factors, vehicle shares and diurnal cycles derived from link counts."""

    def __init__(self,
                 link_counts: pd.DataFrame,
                 day_types: pd.Series,
                 reference_year: int,
                 reference_day_type: int = 0,
                 day_groups: Mapping[int, int] | None = None,
                 share_pools: Sequence[tuple[Sequence[str], Sequence[str]]] = ()) -> None:
        """
        Args:
            link_counts: LINK_COUNTS rows (at least the columns in _REQUIRED)
            day_types: day type per date, must cover all dates of the counts
            reference_year: normalisation year, must match the traffic model year
            reference_day_type: day type the annual cycle is normalised to
            day_groups: day type -> group for gap filling and hourly profiles. None keeps every
                day type on its own (v1); the pipeline uses domain.calendar.DAY_GROUPS
            share_pools: (vehicle classes, scaling road types) pairs: the share of these classes is
                computed over the counters of all these road types together, see _pool_shares.
                () computes every share per road type (v1)

        Raises:
            ValueError: if columns, vehicle classes or day types are missing
        """
        missing_columns = set(_REQUIRED) - set(link_counts.columns)
        if missing_columns:
            raise ValueError(f'link_counts lacks the columns {sorted(missing_columns)}')
        missing_classes = set(VEHICLE_CLASSES + ['SUM']) - set(link_counts['vehicle_class'])
        if missing_classes:
            raise ValueError(f'link_counts lacks the vehicle classes {sorted(missing_classes)}')

        self.reference_year = reference_year
        self.reference_day_type = reference_day_type
        self.date_start = link_counts['date'].min()
        self.date_end = link_counts['date'].max()
        self.road_types = sorted(link_counts['scaling_road_type'].unique())

        days = pd.date_range(self.date_start, self.date_end, name='date')
        uncovered = days.difference(pd.DatetimeIndex(day_types.index))
        if len(uncovered) > 0:
            raise ValueError(f'No day type for {len(uncovered)} dates, e.g. {list(uncovered[:3])}')
        self._day_groups = day_groups
        self._share_pools = [(list(classes), list(road_types)) for classes, road_types in share_pools]
        pooled = [(vc, rt) for classes, road_types in self._share_pools for vc in classes for rt in road_types]
        if len(pooled) != len(set(pooled)):
            raise ValueError('A vehicle class is pooled twice on the same scaling road type')
        unknown = {vc for vc, _ in pooled} - set(VEHICLE_CLASSES)
        if unknown:
            raise ValueError(f'Unknown vehicle classes in share_pools: {sorted(unknown)}')
        self._day_types = group_day_types(day_types, day_groups)  # references use link_counts['day_type'] instead

        unknown_road_types = {rt for _, road_types in self._share_pools for rt in road_types} - set(self.road_types)
        if unknown_road_types:
            raise ValueError(f'share_pools name scaling road types without counts: {sorted(unknown_road_types)}')
        self.vehicle_shares = self._calc_vehicle_shares(link_counts)
        self.annual_cycles = self._calc_annual_cycles(link_counts)
        self.daily_cycles = self._calc_daily_cycles(link_counts)

        self.timeprofile: dict[str, pd.DataFrame] = {}
        self.missing_days: dict[str, pd.DatetimeIndex] = {}  # road type -> days set to zero in timeprofile
        for road_type in self.road_types:
            self.timeprofile[road_type], self.missing_days[road_type] = self._combine_time_profile(road_type, days)

    def _calc_vehicle_shares(self, link_counts: pd.DataFrame) -> pd.Series:
        """Share per (vehicle_class, scaling_road_type, date), from complete and valid links."""
        rows = link_counts[link_counts['complete'] & link_counts['valid'] &
                           link_counts['vehicle_class'].isin(VEHICLE_CLASSES)]
        shares = self._median_shares(rows, 'scaling_road_type')
        for classes, road_types in self._share_pools:
            shares = self._pool_shares(shares, rows, classes, road_types)
        return shares.sort_index().rename('share')

    def _median_shares(self, rows: pd.DataFrame, group: str | pd.Series) -> pd.Series:
        """Median daily volume per class over the links of a group, gap-filled, divided by the sum over the classes."""
        keys = [rows['vehicle_class'], rows[group] if isinstance(group, str) else group, rows['date']]
        median = rows['daily_value'].groupby(keys).median()
        median.index.names = _SHARE_LEVELS
        median = fill_gaps(median, self._day_types)
        total = median.groupby(level=['scaling_road_type', 'date']).sum()
        # pandas-stubs only accepts level positions, pandas also takes names
        return (median / total).reorder_levels(_SHARE_LEVELS)  # pyright: ignore[reportArgumentType]

    def _pool_shares(self, shares: pd.Series, rows: pd.DataFrame, classes: list[str], road_types: list[str]) -> pd.Series:
        """Replaces the shares of `classes` on `road_types` by their share over the links of all these road types.

        The pooled share comes from the medians over the pooled links, like a road type's own share. The
        other classes keep their road type's shares, scaled so that the shares of a day add up to 1 again.
        """
        in_pool = rows['scaling_road_type'].isin(road_types)
        pool = self._median_shares(rows[in_pool], pd.Series('pool', index=rows.index)[in_pool])
        pooled = pool[pool.index.get_level_values('vehicle_class').isin(classes)].droplevel('scaling_road_type')
        pooled_sum = pooled.groupby(level='date').sum()
        parts = []
        for road_type, own in shares.groupby(level='scaling_road_type'):
            if road_type not in road_types:
                parts.append(own.reorder_levels(_SHARE_LEVELS))  # pyright: ignore[reportArgumentType]
                continue
            own = own.droplevel('scaling_road_type')
            others = own[~own.index.get_level_values('vehicle_class').isin(classes)]
            dates = others.index.get_level_values('date')
            scale = (1 - pooled_sum.reindex(dates).to_numpy()) / others.groupby(level='date').transform('sum')
            mine = pooled[pooled.index.get_level_values('date').isin(dates.unique())]
            part = pd.concat({road_type: pd.concat([others * scale.to_numpy(), mine])}, names=['scaling_road_type'])
            parts.append(part.reorder_levels(_SHARE_LEVELS))  # pyright: ignore[reportArgumentType]
        return pd.concat(parts)

    def _calc_annual_cycles(self, link_counts: pd.DataFrame) -> pd.Series:
        """Daily scaling per (scaling_road_type, date): SUM volumes normalised per link to the
        IQR mean of its reference days, median over the links."""
        totals = link_counts[link_counts['vehicle_class'] == 'SUM']
        reference = totals[(totals['date'].dt.year == self.reference_year) &
                           (totals['day_type'] == self.reference_day_type) &
                           totals['complete']]
        reference_mean = reference.groupby('road_link_id')['daily_value'].apply(iqr_mean)

        totals = totals[totals['road_link_id'].isin(reference_mean.index)]
        normalised = totals['daily_value'] / totals['road_link_id'].map(reference_mean)
        median = normalised.groupby([totals['scaling_road_type'], totals['date']]).median()
        return fill_gaps(median, self._day_types).rename('scaling')

    def _calc_daily_cycles(self, link_counts: pd.DataFrame) -> pd.DataFrame:
        """Normalised hourly profile per (year, month, day_type, vehicle_class), from the monthly
        median over all rows. Months without data in a group between its first and last month
        stay as NaN rows."""
        grouped = link_counts.assign(day_type=group_day_types(link_counts['day_type'], self._day_groups))
        cycles = grouped.set_index('date').groupby(['day_type', 'vehicle_class'])[HOURS] \
            .resample('ME').median()
        cycles = cycles.div(cycles.sum(axis=1), axis=0).reset_index()
        cycles.insert(2, 'month', cycles['date'].dt.month)
        cycles.insert(2, 'year', cycles['date'].dt.year)
        return cycles.drop(columns='date').set_index(['year', 'month', 'day_type', 'vehicle_class']).sort_index()

    def _combine_time_profile(self, road_type: str, days: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
        """Hourly activity per vehicle class: annual cycle x vehicle share x diurnal cycle.

        A day is missing if its annual cycle, its shares or one of its diurnal cycles has no entry.
        Entries that exist but are NaN stay NaN, as in v1.
        """
        n = len(days)
        activity = self.annual_cycles.xs(road_type, level='scaling_road_type')
        shares = self.vehicle_shares.xs(road_type, level='scaling_road_type').unstack('vehicle_class') \
            .reindex(columns=VEHICLE_CLASSES)
        has_data = days.isin(activity.index) & days.isin(shares.index)

        day_type = self._day_types.reindex(days).to_numpy()
        cycle_values = self.daily_cycles[HOURS].to_numpy()

        def cycle_positions(vehicle_class: str) -> np.ndarray:
            keys = pd.MultiIndex.from_arrays([days.year, days.month, day_type, [vehicle_class] * n])
            return self.daily_cycles.index.get_indexer(keys)

        has_data &= cycle_positions('SUM') >= 0  # v1 raised on a missing SUM cycle as well
        profile = np.zeros((n * 24, len(VEHICLE_CLASSES)))
        activity_values = activity.reindex(days).to_numpy()[:, None]
        for i, vc in enumerate(VEHICLE_CLASSES):
            positions = cycle_positions(vc)
            has_data &= positions >= 0
            share = shares[vc].reindex(days).to_numpy()[:, None]
            profile[:, i] = (cycle_values[positions] * activity_values * share).ravel()
        profile[np.repeat(~has_data, 24)] = 0

        index = pd.date_range(days[0], periods=n * 24, freq='1h', name='time')
        return pd.DataFrame(profile, index=index, columns=VEHICLE_CLASSES), days[~has_data]

    def get_daily_scaling_factors(self, date: str | pd.Timestamp) -> pd.Series:
        """Daily scaling factor per scaling road type."""
        return self.annual_cycles.xs(pd.Timestamp(date), level='date')

    def get_vehicle_share(self, date: str | pd.Timestamp) -> pd.DataFrame:
        """Vehicle shares with scaling road types as rows and vehicle classes as columns."""
        return self.vehicle_shares.xs(pd.Timestamp(date), level='date').unstack('vehicle_class')

    def get_hourly_scaling_factors(self, date: str | pd.Timestamp) -> pd.DataFrame:
        """Diurnal cycle of the date's year, month and day type, per vehicle class (without SUM)."""
        date = pd.Timestamp(date)
        # pandas-stubs has no overload for a partial MultiIndex key
        cycle = self.daily_cycles.loc[(date.year, date.month, int(self._day_types[date]))]  # pyright: ignore[reportCallIssue, reportArgumentType]
        return cycle.drop('SUM')
