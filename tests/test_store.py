"""Batch versions of the DuckDB store, on a temporary file. All counts are invented."""

import pandas as pd

from drive import store
from drive.schemas import HOURS, RAW_COUNTS


def counts(values: dict[str, float]) -> pd.DataFrame:
    """One day of SUM volumes, detector id -> daily value."""
    return RAW_COUNTS.validate(pd.DataFrame([
        {'source': 'LHM', 'detector_id': detector, 'detector_type': None, 'date': pd.Timestamp('2025-03-04'),
         'vehicle_class': 'SUM', 'metric': 'volume', 'daily_value': value, **{h: value / 24 for h in HOURS}}
        for detector, value in values.items()]))


def test_reads_are_pinned_to_a_batch(tmp_path):
    """Batch 2 corrects detector A and doesn't contain detector B.

    The latest read must take A from batch 2 and keep B from batch 1 (the latest batch per key,
    not the latest batch as a whole). A read pinned to batch 1 must give the original A.
    Catches reads that ignore `data_version`, so a run can't be reproduced, and reads that drop
    keys missing from the newest batch.
    """
    path = tmp_path / 'drive.duckdb'
    first = store.write_batch(path, 'counts', 'test', 'first.csv', 'sha-1', {}, {'counts': counts({'A': 100.0, 'B': 50.0})})
    second = store.write_batch(path, 'counts', 'test', 'second.csv', 'sha-2', {}, {'counts': counts({'A': 120.0})})

    def read(version):
        rows = store.read_counts(path, version)
        return dict(zip(rows['detector_id'], zip(rows['daily_value'], rows['batch_id'])))

    assert read(None) == {'A': (120.0, second), 'B': (50.0, first)}
    assert read(first) == {'A': (100.0, first), 'B': (50.0, first)}
