"""Pipeline: the only place where config, store, adapters and domain code meet (spec §4.3)."""

import time
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from drive import store
from drive.config import DriveConfig
from drive.domain.activity import Activity
from drive.domain.calendar import DAY_GROUPS, OUTLIER_GROUPS, calendar_day_types, combined_day_types
from drive.domain.counts_qa import QAParams, QAReport, link_attributes, link_volumes, qa_link_counts
from drive.domain.kernel import (EfTable, HotEmissions, KernelParams, build_aggregated_ef_table, build_ef_table,
                                 hot_emissions, profile_frame, share_corrections)
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


def _day_groups(config: DriveConfig) -> dict[int, int] | None:
    """Groups of the day types; v1's day types are their own groups."""
    return DAY_GROUPS if config.run.calendar_source == 'store' else None


def load_link_counts(config: DriveConfig) -> tuple[pd.DataFrame, QAReport, int]:
    """Quality-controlled link counts (LINK_COUNTS) of the run's traffic model.

    Returns:
        link counts, QA report, and the store batch id the data was read at
    """
    run, qa = _require(config)
    version = store.resolve_version(config.paths.store, run.data_version)
    raw = store.read_counts(config.paths.store, version, metric='volume',
                            start=qa.period_start.isoformat(), end=qa.period_end.isoformat())
    links = store.read_counter_links(config.paths.store, run.traffic_model, version)
    attributes = link_attributes(store.read_links(config.paths.store, run.traffic_model, version))

    params = QAParams(reference_year=run.reference_year,
                      reference_day_type=run.reference_day_type,
                      completeness_window=tuple(d.isoformat() for d in qa.completeness_window),
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


def clip_links(links: gpd.GeoDataFrame, boundary_path) -> gpd.GeoDataFrame:
    """Clips links to a boundary, as v1 does. A link split by the boundary gives one row per `piece`."""
    boundary = gpd.read_file(boundary_path).to_crs(links.crs)
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
    links = store.read_links(config.paths.store, run.traffic_model, version)
    if config.paths.clip_boundary is not None:
        links = clip_links(links, config.paths.clip_boundary)
    else:
        links = links.assign(piece=0)
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
    return HotRun(links, corrections, hot, ef, dates, version, report, seconds)


def hot_profile(run: HotRun, config: DriveConfig) -> pd.DataFrame:
    """Hourly emissions in g per road type, vehicle class and component, length-weighted over all roads."""
    return profile_frame(run.hot.profiles['length_km'], run.dates, run.ef, kernel_params(config)) \
        .rename(columns={'emission': 'emission_g'})


def hot_results(run: HotRun) -> pd.DataFrame:
    """Result table: g/km per link and piece, with the attributes needed to summarise it."""
    keys = run.links[['road_link_id', 'from_node', 'piece', 'road_type', 'scaling_road_type']].copy()
    keys['length_km'] = run.links.length / 1000
    return pd.concat([keys, run.hot.emissions], axis=1)
