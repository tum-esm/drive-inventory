"""Command line interface: `drive ingest <source> <config>` (later also `drive run`, `drive export`)."""

import argparse
import sys

from drive import __version__, store
from drive.config import DriveConfig, load_config
from drive.io import hbefa
from drive.io.counts_preprocessed import read_preprocessed_counts
from drive.io.visum import read_links, read_zones
from drive.domain.kernel import scaling_factors
from drive.pipeline import compute_hot_emissions, hot_profile, hot_results


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


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    run = compute_hot_emissions(config)
    results = hot_results(run)
    profile = hot_profile(run, config)
    config.paths.results.mkdir(parents=True, exist_ok=True)
    stem = f'{config.run.traffic_model}_{config.run.start.year}_hbefa{config.run.hbefa_version}_batch{run.version}'
    name = f'hot_{stem}.parquet'
    results.to_parquet(config.paths.results / name)
    profile.to_parquet(config.paths.results / f'hot_profile_{stem}.parquet')
    scaling_factors(profile.rename(columns={'emission_g': 'emission'})) \
        .to_csv(config.paths.results / f'hot_timeprofile_{stem}.csv', index=False)
    timing = ', '.join(f'{stage} {value:.1f} s' for stage, value in run.seconds.items())
    print(f'{config.paths.results / name}: {len(results)} rows, store batch {run.version}')
    print(f'Time: {timing}; links with negative volumes: {run.hot.negative_volume_links}')
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
    ef.set_defaults(func=_ingest_hbefa)
    visum = sources.add_parser('visum', help='links and zones of the models under traffic_models')
    visum.add_argument('config', help='path to the run configuration (YAML)')
    visum.set_defaults(func=_ingest_visum)

    compute = commands.add_parser('run', help='compute the annual hot emissions of a run')
    compute.add_argument('config', help='path to the run configuration (YAML)')
    compute.set_defaults(func=_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
