"""Pipeline: the only place where config, store, adapters and domain code meet (spec §4.3)."""

import time
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from drive import store
from drive.config import DriveConfig
from drive.domain.activity import Activity
from drive.domain.calendar import DAY_GROUPS, OUTLIER_GROUPS, calendar_day_types, combined_day_types
from drive.domain.cold_start import StartsReport, distribute_starts, hourly_cold_emissions, link_cold_emissions
from drive.domain.counts_qa import QAParams, QAReport, link_attributes, link_volumes, qa_link_counts
from drive.domain.kernel import (
    EfTable,
    HotEmissions,
    KernelParams,
    build_aggregated_ef_table,
    build_ef_table,
    hot_emissions,
    profile_frame,
    reference_shares,
    scaling_factors,
    share_corrections,
)
from drive.domain.meteo import TemperatureReport, combine_stations, station_series, to_local_hourly
from drive.io.boundaries import LAND
from drive.io.calendar_excel import read_calendar


def _require(config: DriveConfig):
    if config.run is None or config.counts_qa is None:
        raise ValueError('The config needs the run and counts_qa sections')
    return config.run, config.counts_qa


def kernel_params(config: DriveConfig) -> KernelParams:
    run, _ = _require(config)
    if config.kernel is None or not run.vehicle_classes or not run.components:
        raise ValueError('The config needs the kernel section and run.vehicle_classes and run.components')
    return KernelParams(vehicle_classes=run.vehicle_classes,
                        components=run.components,
                        car_unit_factors=config.kernel.car_unit_factors,
                        vcr_thresholds=config.kernel.vcr_thresholds,
                        area_type=run.area_type)


def load_hot_factors(config: DriveConfig, year: int, version: int) -> pd.DataFrame:
    """Hot emission factors of one year for the run's mode, ambient pattern and area type."""
    run, _ = _require(config)
    if run.hbefa_version is None or run.hot_ambient_pattern is None:
        raise ValueError('The config needs run.hbefa_version and run.hot_ambient_pattern')
    aggregation = 'aggregate_ts' if run.hot_mode == 'aggregated' else 'single_ts'
    factors = store.read_emission_factors(config.paths.store, run.hbefa_version, year, 'hot', aggregation,
                                          run.components, version)
    selected = factors[factors['ambient_pattern'] == run.hot_ambient_pattern]
    if run.hot_mode == 'aggregated':
        selected = selected[selected['road_category'] == run.area_type]
    if selected.empty:
        raise ValueError(f'No {year} hot factors with the ambient pattern {run.hot_ambient_pattern}')
    return selected


def load_day_types(config: DriveConfig, version: int | None = None) -> pd.Series:
    """Day type per date for the counts period and the run.

    Args:
        version: store batch id to read at, None = run.data_version

    Raises:
        ValueError: if the calendar doesn't cover the counts period and the run
    """
    run, qa = _require(config)
    first = min(qa.period_start, run.start or qa.period_start).year
    last = max(qa.period_end, run.end or qa.period_end).year
    if run.calendar_source == 'v1_workbook':
        return combined_day_types(read_calendar(config.paths.calendar, list(range(first, last + 1))))

    c = config.ingest.calendar
    if c is None:
        raise ValueError('No ingest.calendar section in the config')
    calendar = store.read_calendar(config.paths.store, f'{c.country}-{c.subdivision}',
                                   run.data_version if version is None else version)
    day_types = calendar_day_types(calendar)
    if day_types.index.min().year > first or day_types.index.max().year < last:
        raise ValueError(f'The calendar covers {day_types.index.min().year} to {day_types.index.max().year}, '
                         f'the counts period and the run need {first} to {last}')
    return day_types


def load_temperature(config: DriveConfig,
                     index: pd.DatetimeIndex,
                     version: int | None = None) -> tuple[pd.Series, TemperatureReport]:
    """Hourly ambient temperature on a local, naive hourly index: main station, gaps from the backup
    station, converted to local time (v1 notebook 11).

    Args:
        version: store batch id to read at, None = run.data_version
    """
    run, _ = _require(config)
    t = run.temperature
    if t is None:
        raise ValueError('The config needs run.temperature')
    at = run.data_version if version is None else version
    # local hours lie within a day of UTC; the margin also covers the hours interpolation looks at
    start = (index.min() - pd.Timedelta(days=1)).to_pydatetime()
    end = (index.max() + pd.Timedelta(days=1)).to_pydatetime()

    def read(station: str) -> pd.Series:
        return station_series(store.read_temperatures(config.paths.store, station, start, end, at))

    main, from_backup = combine_stations(read(t.station), read(t.backup_station) if t.backup_station else None)
    temperature, interpolated = to_local_hourly(main, index, t.timezone, t.max_gap_hours)
    return temperature, TemperatureReport(from_backup=from_backup, interpolated=interpolated)


def _day_groups(config: DriveConfig) -> dict[int, int] | None:
    """Groups of the day types; v1's day types are their own groups."""
    run, _ = _require(config)
    return DAY_GROUPS if run.calendar_source == 'store' else None


def load_link_counts(config: DriveConfig) -> tuple[pd.DataFrame, QAReport, int]:
    """Quality-controlled link counts (LINK_COUNTS) of the run's traffic model.

    Returns:
        link counts, QA report, and the store batch id the data was read at
    """
    run, qa = _require(config)
    version = store.resolve_version(config.paths.store, run.data_version)
    raw = store.read_counts(config.paths.store, version, metric='volume', linked_in=run.traffic_model,
                            start=qa.period_start.isoformat(), end=qa.period_end.isoformat())
    links = store.read_counter_links(config.paths.store, run.traffic_model, version)
    attributes = link_attributes(store.read_links(config.paths.store, run.traffic_model, version))

    params = QAParams(reference_year=run.reference_year,
                      reference_day_type=run.reference_day_type,
                      completeness_window=(qa.completeness_window[0].isoformat(), qa.completeness_window[1].isoformat()),
                      hourly_daily_tolerance=qa.hourly_daily_tolerance,
                      min_daily_value=qa.min_daily_value,
                      outlier_z_threshold=qa.outlier_z_threshold,
                      sqv_f=qa.sqv_f,
                      sqv_threshold=qa.sqv_threshold,
                      completeness_threshold=qa.completeness_threshold,
                      iqr_range=qa.iqr_range,
                      scaling_road_types=config.scaling_road_types,
                      outlier_groups=OUTLIER_GROUPS if run.calendar_source == 'store' else None)

    raw['date'] = raw['date'].astype('datetime64[us]')
    volume = link_volumes(raw, links, attributes, load_day_types(config, version))
    link_counts, report = qa_link_counts(volume, attributes, params)
    return link_counts, report, version


def load_activity(config: DriveConfig) -> tuple[Activity, QAReport, int]:
    """Traffic activity of the run: store -> counts QA -> Activity.

    Returns:
        activity, QA report, and the store batch id the data was read at
    """
    run, _ = _require(config)
    link_counts, report, version = load_link_counts(config)
    activity = Activity(link_counts, load_day_types(config, version), run.reference_year, run.reference_day_type,
                        _day_groups(config))
    return activity, report, version


def load_link_starts(config: DriveConfig, version: int | None = None) -> tuple[gpd.GeoDataFrame, StartsReport]:
    """Links of the run's traffic model (not clipped) with their daily starts per vehicle class.

    Args:
        version: store batch id to read at, None = run.data_version
    """
    run, _ = _require(config)
    c = config.cold_start
    if c is None:
        raise ValueError('The config needs the cold_start section')
    at = run.data_version if version is None else version
    links = store.read_links(config.paths.store, run.traffic_model, at)
    zones = store.read_zones(config.paths.store, run.traffic_model, at)
    starts, report = distribute_starts(links, zones, c.vehicle_classes, c.road_types, c.buffer_m)
    return gpd.GeoDataFrame(pd.concat([links, starts], axis=1), geometry='geometry', crs=links.crs), report


@dataclass
class HotRun:
    links: gpd.GeoDataFrame  # the links of the run after clipping, with road_link_id, from_node, piece
    corrections: pd.DataFrame
    hot: HotEmissions
    ef: EfTable
    dates: pd.DatetimeIndex
    version: int  # store batch id the data was read at
    report: QAReport
    seconds: dict[str, float]  # wall time per stage
    activity: Activity


def load_clip_boundary(config: DriveConfig, version: int | None = None) -> gpd.GeoDataFrame | None:
    """The run's clip area: VG250 land area of run.clip_ags from the store, or v1's file; None = no clipping.

    Args:
        version: store batch id to read at, None = run.data_version
    """
    run, _ = _require(config)
    if run.clip_source == 'v1_file':
        if config.paths.clip_boundary is None:
            raise ValueError('run.clip_source v1_file needs paths.clip_boundary')
        return gpd.read_file(config.paths.clip_boundary)
    if run.clip_ags is None:
        return None
    return store.read_boundary(config.paths.store, run.clip_ags, gf=LAND,
                               data_version=run.data_version if version is None else version)


def clip_to(links: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame | None) -> gpd.GeoDataFrame:
    """Links clipped to the boundary with a `piece` per part, or all links as piece 0 without one."""
    return links.assign(piece=0) if boundary is None else clip_links(links, boundary)


def clip_links(links: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Clips links to a boundary, as v1 does. A link split by the boundary gives one row per `piece`."""
    if links.crs is None:
        raise ValueError('The links have no CRS, so they cannot be clipped')
    boundary = boundary.to_crs(links.crs)
    clipped = gpd.clip(links, boundary).explode(index_parts=True)
    clipped['piece'] = clipped.index.get_level_values(1)
    return clipped.reset_index(drop=True)


def compute_hot_emissions(config: DriveConfig) -> HotRun:
    """Annual hot emissions per link of the run: store -> counts QA -> Activity -> kernel."""
    run, _ = _require(config)
    if run.start is None or run.end is None:
        raise ValueError('The config needs run.start and run.end')
    if run.start.year != run.end.year:
        raise ValueError(f'A run covers one calendar year for now, got {run.start} to {run.end}')

    seconds = {}
    start = time.perf_counter()
    activity, report, version = load_activity(config)
    seconds['activity'] = time.perf_counter() - start

    start = time.perf_counter()
    links = clip_to(store.read_links(config.paths.store, run.traffic_model, version),
                    load_clip_boundary(config, version))
    params = kernel_params(config)
    corrections = share_corrections(links, activity.vehicle_shares, load_day_types(config, version), run.reference_year,
                                    run.reference_day_type)
    factors = load_hot_factors(config, run.start.year, version)
    ef = build_aggregated_ef_table(links, factors, params) if run.hot_mode == 'aggregated' \
        else build_ef_table(links, factors, params)
    seconds['links and factors'] = time.perf_counter() - start

    start = time.perf_counter()
    dates = pd.date_range(run.start, run.end)
    hot = hot_emissions(links, corrections, activity, dates, ef, params,
                        profile_weights={'length_km': links.length.to_numpy() / 1000})
    seconds['kernel'] = time.perf_counter() - start
    return HotRun(links, corrections, hot, ef, dates, version, report, seconds, activity)


def hot_profile(run: HotRun, config: DriveConfig) -> pd.DataFrame:
    """Hourly emissions in g per road type, vehicle class and component, length-weighted over all roads."""
    return profile_frame(run.hot.profiles['length_km'], run.dates, run.ef, kernel_params(config)) \
        .rename(columns={'emission': 'emission_g'})


def hot_results(run: HotRun) -> pd.DataFrame:
    """Result table: g/km per link and piece, with the attributes needed to summarise it."""
    keys = run.links[['road_link_id', 'from_node', 'piece', 'road_type', 'scaling_road_type']].copy()
    keys['length_km'] = run.links.length / 1000
    return pd.concat([keys, run.hot.emissions], axis=1)


@dataclass
class ColdRun:
    links: gpd.GeoDataFrame  # the links of the run after clipping, with road_link_id, from_node, piece
    emissions: pd.DataFrame  # g per link piece and period, columns {vehicle_class}_{component}
    hourly: pd.DataFrame  # time, vehicle_class, component, emission_g
    daily_starts: dict[str, float]  # starts per normal weekday within the clip boundary
    starts: StartsReport
    temperature: TemperatureReport
    version: int


def compute_cold_emissions(config: DriveConfig, activity: Activity | None = None,
                           version: int | None = None) -> ColdRun:
    """Cold start excess emissions of the run (v1 notebook 11).

    Starts per link and day come from the traffic model's zones (domain.cold_start). Within the clip
    boundary they are counted by clipped length. Each hour's starts are the daily starts times the
    hourly activity of the class on `cold_start.profile_road_type`: daily scaling x share x diurnal cycle
    of the class, divided by the class's share on the reference days (`start_scaling: vehicle_specific`,
    R40) or, as in v1, not (`v1_share`). Factors follow the hour's temperature. The period's totals are distributed to the clipped
    link pieces by the starts of their whole link, as in v1 (backlog R39).

    Args:
        activity, version: from a hot run of the same config, to avoid computing them twice
    """
    run, _ = _require(config)
    c = config.cold_start
    if c is None or run.start is None or run.end is None or run.hbefa_version is None:
        raise ValueError('The config needs the cold_start section, run.start, run.end and run.hbefa_version')
    if activity is None or version is None:
        activity, _, version = load_activity(config)

    links, starts_report = load_link_starts(config, version)
    columns = [f'{vc}_starts' for vc in c.vehicle_classes]
    per_metre = links[columns].div(links.length, axis=0).add_suffix('_per_m')
    links = clip_to(pd.concat([links, per_metre], axis=1), load_clip_boundary(config, version))
    daily_starts = {vc: float((links[f'{vc}_starts_per_m'] * links.length).sum()) for vc in c.vehicle_classes}

    days = pd.date_range(run.start, run.end)
    hours = pd.date_range(days[0], periods=len(days) * 24, freq='1h')
    missing = activity.missing_days[c.profile_road_type].intersection(days)
    if len(missing) > 0:
        raise ValueError(f'No hourly activity of {c.profile_road_type} on {len(missing)} days, e.g. {list(missing[:3])}')
    profile = activity.timeprofile[c.profile_road_type].reindex(hours)
    if c.start_scaling == 'vehicle_specific':
        shares = reference_shares(activity.vehicle_shares, load_day_types(config, version), run.reference_year,
                                  run.reference_day_type).xs(c.profile_road_type, level='scaling_road_type')
        profile = profile[c.vehicle_classes] / shares[c.vehicle_classes]
    hourly_starts = pd.DataFrame({vc: daily_starts[vc] * profile[vc] for vc in c.vehicle_classes}, index=hours)

    temperature, temperature_report = load_temperature(config, hours, version)
    factors = store.read_emission_factors(config.paths.store, run.hbefa_version, run.start.year, 'start',
                                          'aggregate_ts', c.components, version)
    hourly = hourly_cold_emissions(temperature, hourly_starts, factors, c.components)
    totals = hourly.groupby(['vehicle_class', 'component'], sort=False)['emission_g'].sum()

    weights = links[columns].set_axis(c.vehicle_classes, axis=1)
    emissions = link_cold_emissions(weights, totals)
    return ColdRun(links, emissions, hourly, daily_starts, starts_report, temperature_report, version)


def cold_results(run: ColdRun) -> pd.DataFrame:
    """Result table: g/km per link and piece, like hot_results."""
    keys = run.links[['road_link_id', 'from_node', 'piece', 'road_type', 'scaling_road_type']].copy()
    keys['length_km'] = run.links.length / 1000
    return pd.concat([keys, run.emissions.div(keys['length_km'], axis=0)], axis=1)


def run_inventory(config: DriveConfig) -> list[str]:
    """Hot and, with a cold_start section, cold start emissions of the run, written to paths.results.

    Returns:
        log lines: written files, timing and run reports
    """
    run_config, _ = _require(config)
    results = config.paths.results
    results.mkdir(parents=True, exist_ok=True)
    log = []

    hot = compute_hot_emissions(config)
    mode = '_aggregated' if run_config.hot_mode == 'aggregated' else ''
    stem = f'{run_config.traffic_model}_{hot.dates[0].year}_hbefa{run_config.hbefa_version}_batch{hot.version}'
    table = hot_results(hot)
    profile = hot_profile(hot, config)
    table.to_parquet(results / f'hot_{stem}{mode}.parquet')
    profile.to_parquet(results / f'hot_profile_{stem}{mode}.parquet')
    scaling_factors(profile.rename(columns={'emission_g': 'emission'})) \
        .to_csv(results / f'hot_timeprofile_{stem}{mode}.csv', index=False)
    timing = ', '.join(f'{stage} {value:.1f} s' for stage, value in hot.seconds.items())
    log += [f'{results / f"hot_{stem}{mode}.parquet"}: {len(table)} rows, store batch {hot.version}',
            f'Time: {timing}; links with negative volumes: {hot.hot.negative_volume_links}']

    if config.cold_start is not None:
        start = time.perf_counter()
        cold = compute_cold_emissions(config, hot.activity, hot.version)
        cold_results(cold).to_parquet(results / f'cold_{stem}.parquet')
        cold.hourly.to_parquet(results / f'cold_profile_{stem}.parquet')
        scaling_factors(cold.hourly.rename(columns={'emission_g': 'emission'})) \
            .to_csv(results / f'cold_timeprofile_{stem}.csv', index=False)
        starts = ', '.join(f'{vc} {value:.0f}' for vc, value in cold.daily_starts.items())
        log.append(f'{results / f"cold_{stem}.parquet"}: {len(cold.links)} rows, {time.perf_counter() - start:.1f} s, '
                   f'start scaling {config.cold_start.start_scaling}; daily starts within the boundary {starts}; '
                   f'temperature hours from the backup station {cold.temperature.from_backup}, '
                   f'interpolated {cold.temperature.interpolated}')
    return log
