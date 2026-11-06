"""Compare freshly downloaded HBEFA tables with the tables in ingest.hbefa.directory.

Usage: uv run python scripts/compare_hbefa_api.py DOWNLOAD_DIR [--config configs/munich_2025.yaml] [--year 2025]

Downloads the configured tables into DOWNLOAD_DIR (existing files there are kept, so a re-run
makes no new requests) and compares every shared key. The server's results vary slightly between
runs (up to 4e-7 relative on 2025 single_ts, in BC-nx and PM2.5-nx), hence RELATIVE_TOLERANCE. Rows
on only one side are listed per pollutant: requests of different dates can differ in their pollutants.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from drive.config import load_config
from drive.io import hbefa, hbefa_api
from drive.schemas import EF_KEY

RELATIVE_TOLERANCE = 1e-6
VALUES = ['weight', 'efa', 'efa_0', 'efa_100', 'speed', 'speed_0', 'speed_100', 'cum_mileage']


def compare(new: hbefa.EfFile, old: hbefa.EfFile) -> bool:
    key = [k for k in EF_KEY if k != 'hbefa_version']
    left, right = [hbefa.read_table(f).assign(**{k: lambda d, k=k: d[k].fillna('') for k in
                                                 ['process_scope', 'traffic_situation', 'gradient']}) for f in (new, old)]
    merged = left.merge(right, on=key, how='outer', suffixes=('_new', '_old'), indicator=True)
    both = merged[merged['_merge'] == 'both']
    different = [v for v in VALUES if not np.isclose(both[f'{v}_new'], both[f'{v}_old'], rtol=RELATIVE_TOLERANCE,
                                                     atol=0.0, equal_nan=True).all()]
    extra = {side: merged[merged['_merge'] == f'{side}_only']['pollutant'].value_counts().to_dict()
             for side in ('left', 'right')}
    print(f'{new.path.name}: {len(both)} shared keys, values {"DIFFER in " + str(different) if different else f"within {RELATIVE_TOLERANCE}"}; '
          f'only in download {extra["left"]}, only in the directory {extra["right"]}')
    return not different


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--config', default='configs/munich_2025.yaml')
    parser.add_argument('--year', type=int, action='append', help='only these years (default: all configured)')
    args = parser.parse_args()

    ingest = load_config(args.config).ingest.hbefa
    existing = {f.path.name: f for f in hbefa.find_files(ingest.directory, ingest.version)}
    if args.year:
        for table in ingest.api.tables:
            table.years = [y for y in table.years if y in args.year]
    download = ingest.model_copy(update={'directory': args.directory.resolve()})
    hbefa_api.download_missing(download)

    results = [compare(new, existing[new.path.name]) for new in hbefa.find_files(download.directory, ingest.version)]
    print('\nHBEFA API:', 'OK (shared keys within the tolerance)' if all(results) else 'DIFFERENT')
    sys.exit(0 if all(results) else 1)
