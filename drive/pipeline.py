"""Pipeline: the only place where config, store, adapters and domain code meet (spec §4.3)."""

import pandas as pd

from drive import store
from drive.config import DriveConfig
from drive.domain.activity import Activity
from drive.domain.calendar import combined_day_types
from drive.domain.counts_qa import QAParams, QAReport, link_attributes, link_volumes, qa_link_counts
from drive.domain.kernel import KernelParams
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
    """Hot emission factors of one year, level-of-service specific, for the run's ambient pattern."""
    run, _ = _require(config)
    if run.hbefa_version is None or run.hot_ambient_pattern is None:
        raise ValueError('The config needs run.hbefa_version and run.hot_ambient_pattern')
    factors = store.read_emission_factors(config.paths.store, run.hbefa_version, year, 'hot', 'single_ts',
                                          run.components, version)
    selected = factors[factors['ambient_pattern'] == run.hot_ambient_pattern]
    if selected.empty:
        raise ValueError(f'No {year} hot factors with the ambient pattern {run.hot_ambient_pattern}')
    return selected


def load_day_types(config: DriveConfig) -> pd.Series:
    """Combined day types for all years of the counts period."""
    _, qa = _require(config)
    years = list(range(qa.period_start.year, qa.period_end.year + 1))
    return combined_day_types(read_calendar(config.paths.calendar, years))


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
                      scaling_road_types=config.scaling_road_types)

    raw['date'] = raw['date'].astype('datetime64[us]')
    volume = link_volumes(raw, links, attributes, load_day_types(config))
    link_counts, report = qa_link_counts(volume, attributes, params)
    return link_counts, report, version


def load_activity(config: DriveConfig) -> tuple[Activity, QAReport, int]:
    """Traffic activity of the run: store -> counts QA -> Activity.

    Returns:
        activity, QA report, and the store batch id the data was read at
    """
    run, _ = _require(config)
    link_counts, report, version = load_link_counts(config)
    activity = Activity(link_counts, load_day_types(config), run.reference_year, run.reference_day_type)
    return activity, report, version
