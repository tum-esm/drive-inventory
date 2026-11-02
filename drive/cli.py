"""Command line interface: `drive ingest <source> <config>` (later also `drive run`, `drive export`)."""

import argparse
import sys

from drive import __version__, store
from drive.config import load_config
from drive.io.counts_preprocessed import read_preprocessed_counts
from drive.io.visum import read_link_ids


def _ingest_counts(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config.traffic_models:
        raise ValueError('No traffic_models in the config, counter links need at least one')
    print(f'Store: {config.paths.store}')
    model_link_ids = {m: read_link_ids(c.links) for m, c in config.traffic_models.items()}
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='drive', description='DRIVE road transport emission inventory')
    parser.add_argument('--version', action='version', version=f'drive {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)

    ingest = commands.add_parser('ingest', help='load source data into the store')
    sources = ingest.add_subparsers(dest='source', required=True)
    counts = sources.add_parser('counts', help='traffic counts listed under ingest.counts')
    counts.add_argument('config', help='path to the run configuration (YAML)')
    counts.set_defaults(func=_ingest_counts)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
