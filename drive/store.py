"""DuckDB store for ingested data (spec §4.2, D9, D13).

- Append-only: every ingest is a batch in `ingest_batches`; rows are never updated.
  A correction is a new batch, and the latest batch per key wins.
- Versioned reads: `data_version` (a batch id or a timestamp) limits reads to the
  batches up to that version, so a run can be reproduced on a changing store.
- Single writer: only `write_batch` opens a read-write connection. DuckDB holds a file
  lock while it is open; all reads use read-only connections.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from drive.schemas import COUNT_KEY, HOURS

DataVersion = int | datetime | None

_DDL = f"""
CREATE SEQUENCE IF NOT EXISTS batch_id_seq START 1;
CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id     BIGINT PRIMARY KEY,
    kind         VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    ingested_at  TIMESTAMPTZ NOT NULL,
    input_path   VARCHAR NOT NULL,
    input_sha256 VARCHAR NOT NULL,
    params       VARCHAR NOT NULL,
    rows         JSON NOT NULL,
    note         VARCHAR
);
CREATE TABLE IF NOT EXISTS counts (
    batch_id      BIGINT NOT NULL,
    source        VARCHAR NOT NULL,
    detector_id   VARCHAR NOT NULL,
    detector_type VARCHAR,
    date          DATE NOT NULL,
    vehicle_class VARCHAR NOT NULL,
    metric        VARCHAR NOT NULL,
    daily_value   DOUBLE,
    {', '.join(f'{h} DOUBLE' for h in HOURS)}
);
CREATE TABLE IF NOT EXISTS counter_links (
    batch_id      BIGINT NOT NULL,
    source        VARCHAR NOT NULL,
    detector_id   VARCHAR NOT NULL,
    traffic_model VARCHAR NOT NULL,
    road_link_id  BIGINT NOT NULL
);
"""

# table -> key that identifies a row across batches (latest batch wins)
_KEYS = {
    'counts': COUNT_KEY,
    'counter_links': ['source', 'detector_id', 'traffic_model'],
}


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _connect_read(store: Path) -> duckdb.DuckDBPyConnection:
    if not store.exists():
        raise FileNotFoundError(f'Store {store} does not exist, run `drive ingest` first')
    return duckdb.connect(str(store), read_only=True)


def find_batch(store: Path, kind: str, input_sha256: str, params: dict) -> int | None:
    """Batch id of an earlier ingest of the same input with the same parameters, if any."""
    if not store.exists():
        return None
    with _connect_read(store) as con:
        row = con.execute('SELECT batch_id FROM ingest_batches WHERE kind = ? AND input_sha256 = ? AND params = ?',
                          [kind, input_sha256, json.dumps(params, sort_keys=True)]).fetchone()
    return row[0] if row else None


def write_batch(store: Path,
                kind: str,
                source: str,
                input_path: str | Path,
                input_sha256: str,
                params: dict,
                tables: dict[str, pd.DataFrame],
                note: str | None = None) -> int:
    """Writes one batch (a batch record plus rows for one or more tables) in a single transaction.

    The frames must already conform to their contract in drive.schemas.

    Returns:
        int: the new batch id
    """
    unknown = set(tables) - set(_KEYS)
    if unknown:
        raise ValueError(f'Unknown tables {unknown}')

    store.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(store)) as con:
        con.execute(_DDL)
        con.execute('BEGIN TRANSACTION')
        try:
            batch_id = con.execute("SELECT nextval('batch_id_seq')").fetchone()[0]
            con.execute('INSERT INTO ingest_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        [batch_id, kind, source, datetime.now(timezone.utc), str(input_path), input_sha256,
                         json.dumps(params, sort_keys=True),
                         json.dumps({t: len(df) for t, df in tables.items()}), note])
            for table, df in tables.items():
                con.register('_frame', df)
                columns = ', '.join(df.columns)
                con.execute(f'INSERT INTO {table} (batch_id, {columns}) SELECT ?, {columns} FROM _frame', [batch_id])
                con.unregister('_frame')
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
    return batch_id


def resolve_version(store: Path, data_version: DataVersion = None) -> int:
    """Highest batch id covered by `data_version` (None = latest)."""
    with _connect_read(store) as con:
        if data_version is None:
            row = con.execute('SELECT max(batch_id) FROM ingest_batches').fetchone()
        elif isinstance(data_version, datetime):
            if data_version.tzinfo is None:
                raise ValueError('data_version timestamps must be time-zone aware')
            row = con.execute('SELECT max(batch_id) FROM ingest_batches WHERE ingested_at <= ?',
                              [data_version]).fetchone()
        else:
            row = con.execute('SELECT max(batch_id) FROM ingest_batches WHERE batch_id <= ?',
                              [data_version]).fetchone()
    if row[0] is None:
        raise ValueError(f'No batches in {store} up to data_version {data_version}')
    return row[0]


def _read_latest(store: Path, table: str, version: int, where: str = '', params: list | None = None) -> pd.DataFrame:
    key = ', '.join(_KEYS[table])
    query = f"""
        SELECT * EXCLUDE (_rank) FROM (
            SELECT *, row_number() OVER (PARTITION BY {key} ORDER BY batch_id DESC) AS _rank
            FROM {table} WHERE batch_id <= ? {where}
        ) WHERE _rank = 1 ORDER BY {key}
    """
    with _connect_read(store) as con:
        return con.execute(query, [version] + (params or [])).df()


def read_counts(store: Path,
                data_version: DataVersion = None,
                metric: str | None = None,
                start: str | None = None,
                end: str | None = None) -> pd.DataFrame:
    """Raw counts per detector (contract drive.schemas.RAW_COUNTS plus batch_id), latest batch per key.

    Args:
        metric: only this metric ('volume' or 'speed')
        start, end: only dates in [start, end] (ISO dates, inclusive)
    """
    where, params = '', []
    for clause, value in [('metric = ?', metric), ('date >= ?', start), ('date <= ?', end)]:
        if value is not None:
            where += f' AND {clause}'
            params.append(value)
    return _read_latest(store, 'counts', resolve_version(store, data_version), where, params)


def read_counter_links(store: Path, traffic_model: str, data_version: DataVersion = None) -> pd.DataFrame:
    """Detector -> road link mapping of one traffic model, latest batch per detector."""
    return _read_latest(store, 'counter_links', resolve_version(store, data_version),
                        'AND traffic_model = ?', [traffic_model])


def read_batches(store: Path) -> pd.DataFrame:
    with _connect_read(store) as con:
        return con.execute('SELECT * FROM ingest_batches ORDER BY batch_id').df()
