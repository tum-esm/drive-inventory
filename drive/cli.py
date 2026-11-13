"""Command line interface: `drive ingest <source> <config>` (later also `drive run`, `drive export`)."""

import argparse
import hashlib
import sys
import time
from importlib.metadata import version

import pandas as pd

from drive import __version__, store
from drive.config import DriveConfig, load_config
from drive.domain.calendar import build_calendar
from drive.domain.kernel import scaling_factors
from drive.io import dwd, hbefa, hbefa_api
from drive.io.calendar_holidays import read_holidays, read_overrides
from drive.io.counts_preprocessed import read_preprocessed_counts
from drive.io.visum import read_links, read_zones
from drive.pipeline import cold_results, compute_cold_emissions, compute_hot_emissions, hot_profile, hot_results
from drive.schemas import TEMPERATURE_KEY


def _read_model_links(config: DriveConfig, model: str):
    if config.visum is None:
        raise ValueError('No visum section in the config')
    c = config.traffic_models[model]
    return read_links(c.links, model, c.crs, c.link_columns, config.visum, config.scaling_road_types)


def _ingest_counts(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config.traffic_models:
        raise ValueError('No traffic_models in the config, counter links need at least one')
    print(f'Store: {config.paths.store}')
    model_link_ids = {m: set(_read_model_links(config, m)[0]['road_link_id']) for m in config.traffic_models}
    params = {'traffic_models': sorted(model_link_ids)}

    for c in config.ingest.counts:
        sha = store.file_sha256(c.path)
        existing = store.find_batch(config.paths.store, 'counts', sha, params)
        if existing is not None:
            print(f'{c.source}: {c.path.name} already ingested as batch {existing}, skipped')
            continue
        counts, links, report = read_preprocessed_counts(c.path, c.source, model_link_ids)
        batch = store.write_batch(config.paths.store, 'counts', c.source, c.path, sha, params,
                                  {'counts': counts, 'counter_links': links},
                                  note='interim adapter counts_preprocessed (v1 preprocessing 11/12)')
        print(f'{c.source}: {c.path.name} -> batch {batch}: {report.rows} rows, {report.detectors} detectors '
              f'({report.detectors_without_link} without link), {report.missing_marker_rows} rows with '
              f'missing-value markers set to NaN')
        for model, missing in report.links_missing_in_model.items():
            print(f'    {model}: {len(missing)} matched links not in the model {missing[:20]}')
    return 0


def _ingest_hbefa(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if config.ingest.hbefa is None:
        raise ValueError('No ingest.hbefa section in the config')
    print(f'Store: {config.paths.store}')
    if args.download:
        hbefa_api.download_missing(config.ingest.hbefa)
    for file in hbefa.find_files(config.ingest.hbefa.directory, config.ingest.hbefa.version):
        sha = store.file_sha256(file.path)
        existing = store.find_batch(config.paths.store, 'emission_factors', sha, {})
        if existing is not None:
            print(f'{file.path.name} already ingested as batch {existing}, skipped')
            continue
        table = hbefa.read_table(file)
        batch = store.write_batch(config.paths.store, 'emission_factors', 'HBEFA', file.path, sha, {},
                                  {'emission_factors': table})
        print(f'{file.path.name} -> batch {batch}: {len(table)} rows')
    return 0


def _ingest_visum(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config.traffic_models or config.visum is None:
        raise ValueError('The config needs the traffic_models and visum sections')
    print(f'Store: {config.paths.store}')
    for model, c in config.traffic_models.items():
        # the conversion rules are part of the identity of a batch: a changed rule is a new ingest
        params = {'traffic_model': model, 'crs': c.crs, 'link_columns': c.link_columns,
                  'visum': config.visum.model_dump(mode='json'), 'scaling_road_types': config.scaling_road_types}
        sha = store.file_sha256(c.links)
        existing = store.find_batch(config.paths.store, 'links', sha, params)
        if existing is not None:
            print(f'{model} links: {c.links.name} already ingested as batch {existing}, skipped')
        else:
            links, r = _read_model_links(config, model)
            batch = store.write_batch(config.paths.store, 'links', 'VISUM', c.links, sha, params, {'links': links})
            print(f'{model} links: {c.links.name} -> batch {batch}: {r.raw_rows} raw rows, dropped {r.below_min_dtv} '
                  f'below min_dtv and {r.excluded_typeno} in excluded TYPENO (DTV {r.excluded_typeno_dtv:.0f}), '
                  f'kept {r.rows} ({r.road_link_ids} ids); road type differs between directions of '
                  f'{r.road_type_ambiguous}')

        params = {'traffic_model': model, 'crs': c.crs, 'zone_columns': c.zone_columns}
        sha = store.file_sha256(c.zones)
        existing = store.find_batch(config.paths.store, 'zones', sha, params)
        if existing is not None:
            print(f'{model} zones: {c.zones.name} already ingested as batch {existing}, skipped')
        else:
            zones = read_zones(c.zones, model, c.crs, c.zone_columns)
            batch = store.write_batch(config.paths.store, 'zones', 'VISUM', c.zones, sha, params, {'zones': zones})
            print(f'{model} zones: {c.zones.name} -> batch {batch}: {len(zones)} zones')
    return 0


def _ingest_calendar(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    c = config.ingest.calendar
    if c is None:
        raise ValueError('No ingest.calendar section in the config')
    print(f'Store: {config.paths.store}')
    region = f'{c.country}-{c.subdivision}'
    years = list(range(c.years[0], c.years[1] + 1))
    public, school = read_holidays(c.country, c.subdivision, years, c.public_categories)
    overrides = read_overrides(c.overrides) if c.overrides is not None else None
    calendar = build_calendar(region, years, public, school, overrides)

    # there is no input file: the generated content is the identity of a batch, so a package update
    # that changes dates is a new ingest, and one that changes nothing is skipped
    sha = hashlib.sha256(calendar.to_csv(index=False).encode()).hexdigest()
    latest = store.latest_batch(config.paths.store, 'calendar', {'region': region})
    if latest is not None and latest[1] == sha:
        print(f'{region} {c.years[0]}-{c.years[1]}: already ingested as batch {latest[0]}, skipped')
        return 0
    source = f'holidays {version("holidays")}'
    batch = store.write_batch(config.paths.store, 'calendar', source, c.overrides or source, sha, {'region': region},
                              {'calendar': calendar})
    print(f'{region} {c.years[0]}-{c.years[1]} -> batch {batch}: {len(calendar)} days from {source}, '
          f'{calendar["override"].notna().sum()} with an override; '
          f'days per day type {calendar["day_type"].value_counts().sort_index().to_dict()}')
    return 0


def _ingest_meteo(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    m = config.ingest.meteo
    if m is None:
        raise ValueError('No ingest.meteo section in the config')
    print(f'Store: {config.paths.store}')
    start = pd.Timestamp(m.years[0], 1, 1) - pd.Timedelta(days=1)
    end = pd.Timestamp(m.years[1] + 1, 1, 1) + pd.Timedelta(days=1)
    for station in m.stations:
        rows, urls = dwd.fetch_temperatures(station, start, end)
        # incremental: only hours that are new or differ from the store (e.g. a 'recent' value replaced by
        # the quality-controlled 'historical' one) form the batch
        try:
            stored = store.read_temperatures(config.paths.store, station, start.to_pydatetime(),
                                             end.to_pydatetime()).drop(columns='batch_id')
        except (ValueError, FileNotFoundError):
            stored = rows.iloc[:0]
        merged = rows.merge(stored, on=TEMPERATURE_KEY, how='left', suffixes=('', '_stored'), indicator=True)
        same = (merged['_merge'] == 'both') \
            & ((merged['air_temperature'] == merged['air_temperature_stored'])
               | (merged['air_temperature'].isna() & merged['air_temperature_stored'].isna())) \
            & (merged['quality_level'] == merged['quality_level_stored']) \
            & (merged['archive'] == merged['archive_stored'])
        new = rows[~same.to_numpy()].reset_index(drop=True)
        dropped = len(set(stored['timestamp_utc']) - set(rows['timestamp_utc']))
        if new.empty:
            print(f'{station}: {len(rows)} hours, all already in the store, skipped')
            continue
        sha = hashlib.sha256(new.to_csv(index=False).encode()).hexdigest()
        batch = store.write_batch(config.paths.store, 'temperatures', 'DWD', ' '.join(urls), sha,
                                  {'station_id': station}, {'temperatures': new})
        counts = new['archive'].value_counts().to_dict()
        print(f'{station} -> batch {batch}: {len(new)} new or changed hours of {len(rows)} '
              f'({new["timestamp_utc"].min()} to {new["timestamp_utc"].max()} UTC, {counts}), '
              f'{new["air_temperature"].isna().sum()} without a value'
              + (f'; {dropped} stored hours no longer delivered, kept' if dropped else ''))
    return 0


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if config.run is None:
        raise ValueError('No run section in the config')
    run = compute_hot_emissions(config)
    results = hot_results(run)
    profile = hot_profile(run, config)
    config.paths.results.mkdir(parents=True, exist_ok=True)
    mode = '_aggregated' if config.run.hot_mode == 'aggregated' else ''
    stem = f'{config.run.traffic_model}_{run.dates[0].year}_hbefa{config.run.hbefa_version}_batch{run.version}{mode}'
    name = f'hot_{stem}.parquet'
    results.to_parquet(config.paths.results / name)
    profile.to_parquet(config.paths.results / f'hot_profile_{stem}.parquet')
    scaling_factors(profile.rename(columns={'emission_g': 'emission'})) \
        .to_csv(config.paths.results / f'hot_timeprofile_{stem}.csv', index=False)
    timing = ', '.join(f'{stage} {value:.1f} s' for stage, value in run.seconds.items())
    print(f'{config.paths.results / name}: {len(results)} rows, store batch {run.version}')
    print(f'Time: {timing}; links with negative volumes: {run.hot.negative_volume_links}')

    if config.cold_start is not None:
        start = time.perf_counter()
        cold = compute_cold_emissions(config, run.activity, run.version)
        cold_stem = f'{config.run.traffic_model}_{run.dates[0].year}_hbefa{config.run.hbefa_version}_batch{cold.version}'
        name = f'cold_{cold_stem}.parquet'
        cold_results(cold).to_parquet(config.paths.results / name)
        cold.hourly.to_parquet(config.paths.results / f'cold_profile_{cold_stem}.parquet')
        scaling_factors(cold.hourly.rename(columns={'emission_g': 'emission'})) \
            .to_csv(config.paths.results / f'cold_timeprofile_{cold_stem}.csv', index=False)
        starts = ', '.join(f'{vc} {value:.0f}' for vc, value in cold.daily_starts.items())
        print(f'{config.paths.results / name}: {len(cold.links)} rows, {time.perf_counter() - start:.1f} s; '
              f'daily starts within the boundary {starts}; temperature hours from the backup station '
              f'{cold.temperature.from_backup}, interpolated {cold.temperature.interpolated}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='drive', description='DRIVE road transport emission inventory')
    parser.add_argument('--version', action='version', version=f'drive {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)

    ingest = commands.add_parser('ingest', help='load source data into the store')
    sources = ingest.add_subparsers(dest='source', required=True)
    counts = sources.add_parser('counts', help='traffic counts listed under ingest.counts')
    counts.add_argument('config', help='path to the run configuration (YAML)')
    counts.set_defaults(func=_ingest_counts)
    ef = sources.add_parser('hbefa', help='emission factor tables in ingest.hbefa.directory')
    ef.add_argument('config', help='path to the run configuration (YAML)')
    ef.add_argument('--download', action='store_true', help='first download the tables under ingest.hbefa.api that are missing')
    ef.set_defaults(func=_ingest_hbefa)
    visum = sources.add_parser('visum', help='links and zones of the models under traffic_models')
    visum.add_argument('config', help='path to the run configuration (YAML)')
    visum.set_defaults(func=_ingest_visum)

    cal = sources.add_parser('calendar', help='day types from the holidays package and the override file')
    cal.add_argument('config', help='path to the run configuration (YAML)')
    cal.set_defaults(func=_ingest_calendar)

    meteo = sources.add_parser('meteo', help='DWD hourly temperatures of the stations under ingest.meteo')
    meteo.add_argument('config', help='path to the run configuration (YAML)')
    meteo.set_defaults(func=_ingest_meteo)

    compute = commands.add_parser('run', help='compute the hot and cold start emissions of a run')
    compute.add_argument('config', help='path to the run configuration (YAML)')
    compute.set_defaults(func=_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
