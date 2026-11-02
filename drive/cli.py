"""Command line interface: `drive ingest <source> <config>` (later also `drive run`, `drive export`)."""

import argparse
import sys

from drive import __version__
from drive.config import load_config


def _ingest_counts(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(f'Store: {config.paths.store}')
    for c in config.ingest.counts:
        print(f'  {c.source:4s} {c.traffic_model}  {c.path}')
    print('Counts ingest is not implemented yet.', file=sys.stderr)
    return 1


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
