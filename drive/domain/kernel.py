"""Vectorised hot emission kernel, successor of v1 hbefa_hot_emissions and hot_emission_process.

For one link the traffic situation depends only on the level of service (LOS) class, and
emissions are linear in volume. So the kernel sums annual volume per (link, LOS, vehicle class)
day by day, and applies the emission factors once at the end. Hourly profiles work the same way:
links with the same road type, speed and gradient share their factors, so volume is summed per
such group before the factors are applied.

Behaviour kept from v1 for comparability (spec §5):
- the hot ambient pattern is fixed (R33 in the backlog)
- a negative share correction `k` gives negative volumes; they are counted, not clamped
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from drive.domain.activity import Activity
from drive.schemas import HOURS

SERVICE_CLASSES = ['Freeflow', 'Heavy', 'Satur.', 'St+Go', 'St+Go2']
N_LOS = len(SERVICE_CLASSES)
_AREA_PREFIX = {'Urban': 'URB', 'Motorway': 'MW', 'Rural': 'RUR'}
_ROAD_TYPE_NAMES = {'Motorway-Nat': 'MW-Nat.', 'Motorway-City': 'MW-City',
                    'TrunkRoad/Primary-National': 'Trunk-Nat.', 'TrunkRoad/Primary-City': 'Trunk-City',
                    'Distributor/Secondary': 'Distr', 'Local/Collector': 'Local',
                    'Access-residential': 'Access'}


@dataclass(frozen=True)
class KernelParams:
    vehicle_classes: list[str]
    components: list[str]
    car_unit_factors: dict[str, float]
    vcr_thresholds: dict[str, tuple[float, ...]]  # road type -> ascending VCR limits of the LOS classes
    area_type: str = 'Urban'


@dataclass(frozen=True)
class EfTable:
    """Emission factors of the links of a run, stored once per group of links that share them."""
    by_group: np.ndarray  # [group, LOS, vehicle class, component]
    group_of_link: np.ndarray  # group per link
    road_type_of_group: np.ndarray  # position in `road_types` per group
    road_types: list[str]


@dataclass
class HotEmissions:
    emissions: pd.DataFrame  # g/km per link, columns <vehicle class>_<component>, index as `links`
    annual_volume: np.ndarray  # vehicles per [link, LOS, vehicle class]
    negative_volume_links: int
    # weight name -> weighted emissions per [hour, road type, vehicle class, component]
    profiles: dict[str, np.ndarray]


def share_corrections(links: pd.DataFrame,
                      vehicle_shares: pd.Series,
                      day_types: pd.Series,
                      reference_year: int,
                      reference_day_type: int = 0) -> pd.DataFrame:
    """Link-level correction of the HGV and LCV shares: the model's share over the counted share.

    The counted share is the mean over the reference days of the reference year, per scaling
    road type.

    Returns:
        pd.DataFrame: hgv_corr and lcv_corr, index as `links`
    """
    days = day_types.index[(day_types.index.year == reference_year) & (day_types == reference_day_type)]
    shares = vehicle_shares[vehicle_shares.index.get_level_values('date').isin(days)]
    mean_shares = shares.groupby(level=['vehicle_class', 'scaling_road_type']).mean()
    road_types = links['scaling_road_type']
    return pd.DataFrame({
        'hgv_corr': links['dtv_HGV'] / links['dtv_SUM'] / road_types.map(mean_shares.loc['HGV']),
        'lcv_corr': links['dtv_LCV'] / links['dtv_SUM'] / road_types.map(mean_shares.loc['LCV']),
    })


def daily_volumes(dtv_day: np.ndarray,
                  shares: np.ndarray,
                  hgv_corr: np.ndarray,
                  lcv_corr: np.ndarray,
                  vehicle_classes: list[str]) -> np.ndarray:
    """Daily volume per [link, vehicle class].

    HGV and LCV are corrected per link, and all other classes get the factor `k` that keeps the
    total unchanged.

    Args:
        dtv_day: scaled daily volume per link
        shares: counted share per [link, vehicle class]
        hgv_corr, lcv_corr: see share_corrections
    """
    hgv, lcv = vehicle_classes.index('HGV'), vehicle_classes.index('LCV')
    k = (1 - hgv_corr * shares[:, hgv] - lcv_corr * shares[:, lcv]) / (1 - shares[:, hgv] - shares[:, lcv])
    factors = np.repeat(k[:, None], len(vehicle_classes), axis=1)
    factors[:, hgv], factors[:, lcv] = hgv_corr, lcv_corr
    return dtv_day[:, None] * shares * factors


def los_classes(pcu: np.ndarray, capacity: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    """LOS class per [link, hour]: the number of thresholds strictly below the volume/capacity ratio.

    Args:
        pcu: volume in passenger car units per [link, hour]
        capacity: hourly capacity per link
        thresholds: ascending limits per [link, limit]
    """
    vcr = pcu / capacity[:, None]
    classes = np.zeros(vcr.shape, dtype=np.int64)
    for limit in thresholds.T:
        classes += vcr > limit[:, None]
    return classes


def traffic_situation(area_type: str, road_type: str, speed: int, los: int) -> str:
    """HBEFA name of a traffic situation, e.g. URB/Distr/50/Freeflow."""
    return f'{_AREA_PREFIX[area_type]}/{_ROAD_TYPE_NAMES[road_type]}/{speed}/{SERVICE_CLASSES[los]}'


def build_ef_table(links: pd.DataFrame, factors: pd.DataFrame, params: KernelParams) -> EfTable:
    """Emission factors of all links, LOS classes, vehicle classes and components.

    Args:
        links: road_type, hbefa_speed, hbefa_gradient per link
        factors: vehicle_class, traffic_situation, gradient, pollutant, efa of one ambient pattern

    Raises:
        ValueError: if a factor key has several rows, or a link needs a factor that doesn't exist
    """
    key = ['traffic_situation', 'vehicle_class', 'gradient', 'pollutant']
    duplicates = factors.duplicated(key)
    if duplicates.any():
        raise ValueError(f'{duplicates.sum()} rows repeat a factor key, e.g.\n{factors.loc[duplicates, key].head(3)}')
    efa = factors.set_index(key)['efa']

    attributes = ['road_type', 'hbefa_speed', 'hbefa_gradient']
    groups = links[attributes].drop_duplicates().reset_index(drop=True)
    wanted = pd.MultiIndex.from_tuples(
        [(traffic_situation(params.area_type, road_type, int(speed), los), vehicle, gradient, component)
         for road_type, speed, gradient in groups.itertuples(index=False)
         for los in range(N_LOS)
         for vehicle in params.vehicle_classes
         for component in params.components], names=key)
    values = efa.reindex(wanted)
    if values.isna().any():
        missing = values.index[values.isna()]
        raise ValueError(f'No emission factor for {len(missing)} keys, e.g. {list(missing[:3])}')

    shape = (len(groups), N_LOS, len(params.vehicle_classes), len(params.components))
    by_group = values.to_numpy().reshape(shape)
    group_of_link = links[attributes].merge(groups.assign(_group=range(len(groups))), on=attributes, how='left')
    codes, road_types = pd.factorize(groups['road_type'])
    return EfTable(by_group, group_of_link['_group'].to_numpy(), codes, list(road_types))


def build_aggregated_ef_table(links: pd.DataFrame, factors: pd.DataFrame, params: KernelParams) -> EfTable:
    """Emission factors from aggregated traffic situations: one factor per vehicle class and component.

    All LOS classes of a link get the same factor, so the kernel needs no separate path. Links
    are grouped by road type to keep the road types in the profiles. Gradient and speed play no role.

    Args:
        links: road_type per link
        factors: vehicle_class, pollutant, efa of one road category and ambient pattern

    Raises:
        ValueError: if a factor key has several rows, or a factor doesn't exist
    """
    key = ['vehicle_class', 'pollutant']
    duplicates = factors.duplicated(key)
    if duplicates.any():
        raise ValueError(f'{duplicates.sum()} rows repeat a factor key, e.g.\n{factors.loc[duplicates, key].head(3)}')
    wanted = pd.MultiIndex.from_product([params.vehicle_classes, params.components], names=key)
    values = factors.set_index(key)['efa'].reindex(wanted)
    if values.isna().any():
        missing = values.index[values.isna()]
        raise ValueError(f'No emission factor for {len(missing)} keys, e.g. {list(missing[:3])}')

    group_of_link, road_types = pd.factorize(links['road_type'])
    matrix = values.to_numpy().reshape(len(params.vehicle_classes), len(params.components))
    by_group = np.broadcast_to(matrix, (len(road_types), N_LOS) + matrix.shape).copy()
    return EfTable(by_group, group_of_link, np.arange(len(road_types)), list(road_types))


def _day_inputs(activity: Activity,
                date: pd.Timestamp,
                road_types: list[str],
                vehicle_classes: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scaling per road type, shares per [road type, class] and diurnal cycle per [hour, class] of one day.

    Raises:
        ValueError: if the activity has no value for this day
    """
    try:
        scaling = activity.get_daily_scaling_factors(date).reindex(road_types).to_numpy()
        shares = activity.get_vehicle_share(date).reindex(index=road_types, columns=vehicle_classes).to_numpy()
        cycle = activity.get_hourly_scaling_factors(date).reindex(index=vehicle_classes, columns=HOURS).to_numpy().T
    except KeyError as error:
        raise ValueError(f'No activity data for {date.date()}: {error}') from error
    if np.isnan(scaling).any() or np.isnan(shares).any() or np.isnan(cycle).any():
        raise ValueError(f'Activity has NaN values on {date.date()}')
    return scaling, shares, cycle


def hot_emissions(links: pd.DataFrame,
                  corrections: pd.DataFrame,
                  activity: Activity,
                  dates: pd.DatetimeIndex,
                  ef: EfTable,
                  params: KernelParams,
                  profile_weights: dict[str, np.ndarray] | None = None) -> HotEmissions:
    """Hot emissions per link over the given dates.

    Args:
        links: dtv_SUM, scaling_road_type, road_type, hour_capacity per link
        corrections: see share_corrections
        dates: the days to sum, usually one year
        ef: see build_ef_table (level-of-service specific) or build_aggregated_ef_table, for the same links
        profile_weights: name -> weight per link. Each gives an hourly profile, the sum of
            g/km x weight per road type. Link length in km gives emissions in g.

    Returns:
        HotEmissions, in g/km per link
    """
    profile_weights = profile_weights or {}
    n = len(links)
    vehicles = params.vehicle_classes
    road_type_codes, road_types = pd.factorize(links['scaling_road_type'])
    road_types = list(road_types)
    dtv = links['dtv_SUM'].to_numpy(dtype=float)
    capacity = links['hour_capacity'].to_numpy(dtype=float)
    hgv_corr = corrections['hgv_corr'].to_numpy()
    lcv_corr = corrections['lcv_corr'].to_numpy()
    thresholds = np.array([params.vcr_thresholds[t] for t in links['road_type']])
    car_units = np.array([params.car_unit_factors[v] for v in vehicles])
    link_offset = np.arange(n)[:, None] * N_LOS

    annual = np.zeros((n * N_LOS, len(vehicles)))
    n_groups = len(ef.by_group)
    group_offset = ef.group_of_link[:, None] * N_LOS
    hour_offset = np.arange(24)[None, :] * n_groups * N_LOS
    n_cells = 24 * n_groups * N_LOS
    profiles = {name: np.zeros((len(dates) * 24, len(ef.road_types), len(vehicles), len(params.components)))
                for name in profile_weights}

    for d, date in enumerate(dates):
        scaling, shares, cycle = _day_inputs(activity, date, road_types, vehicles)
        day = daily_volumes(dtv * scaling[road_type_codes], shares[road_type_codes], hgv_corr, lcv_corr, vehicles)
        hourly = day[:, None, :] * cycle[None, :, :]
        los = los_classes(hourly @ car_units, capacity, thresholds)
        positions = (link_offset + los).ravel()
        cells = (group_offset + los + hour_offset).ravel()
        for v in range(len(vehicles)):
            annual[:, v] += np.bincount(positions, weights=hourly[:, :, v].ravel(), minlength=n * N_LOS)
        for name, weight in profile_weights.items():
            weighted = hourly * weight[:, None, None]
            cell_volume = np.stack([np.bincount(cells, weights=weighted[:, :, v].ravel(), minlength=n_cells)
                                    for v in range(len(vehicles))], axis=-1)
            cell_volume = cell_volume.reshape(24, n_groups, N_LOS, len(vehicles))
            by_group = np.einsum('hgsv,gsvc->hgvc', cell_volume, ef.by_group)
            for r in range(len(ef.road_types)):
                profiles[name][d * 24:(d + 1) * 24, r] = by_group[:, ef.road_type_of_group == r].sum(axis=1)

    volume = annual.reshape(n, N_LOS, len(vehicles))
    emissions = np.einsum('lsv,lsvc->lvc', volume, ef.by_group[ef.group_of_link])
    columns = [f'{v}_{c}' for v in vehicles for c in params.components]
    return HotEmissions(emissions=pd.DataFrame(emissions.reshape(n, -1), index=links.index, columns=columns),
                        annual_volume=volume,
                        negative_volume_links=int((volume < 0).any(axis=(1, 2)).sum()),
                        profiles=profiles)


def profile_frame(profile: np.ndarray,
                  dates: pd.DatetimeIndex,
                  ef: EfTable,
                  params: KernelParams) -> pd.DataFrame:
    """Long table of a profile: time (local wall clock), road_type, vehicle_class, component, emission."""
    times = pd.DatetimeIndex(np.repeat(dates.to_numpy(), 24)) + pd.to_timedelta(np.tile(np.arange(24), len(dates)), unit='h')
    index = pd.MultiIndex.from_product([times, ef.road_types, params.vehicle_classes, params.components],
                                       names=['time', 'road_type', 'vehicle_class', 'component'])
    return pd.DataFrame({'emission': profile.ravel()}, index=index).reset_index()


def scaling_factors(profile: pd.DataFrame) -> pd.DataFrame:
    """Temporal profile as v1 stores it: hourly emission over the year's mean, per component.

    Args:
        profile: see profile_frame
    """
    hourly = profile.groupby(['component', 'time'], as_index=False)['emission'].sum()
    hourly['scaling_factor'] = hourly['emission'] / hourly.groupby('component')['emission'].transform('mean')
    return pd.DataFrame({'year': hourly['time'].dt.year, 'component': hourly['component'],
                         'timestamp': hourly['time'], 'scaling_factor': hourly['scaling_factor']})
