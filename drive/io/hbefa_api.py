"""Client of the HBEFA web API: downloads emission factor tables into the raw table directory (R35).

Replaces v1's notebook data_preprocessing/00. The files then go through the normal file ingest
(`io.hbefa`), so downloaded tables and tables that are already on disk take the same path into
the store. Files are immutable: a table that is on disk is never requested again.

The server echoes `hbversion_int` but doesn't appear to select data by it (2026-11-06, 2025 start
factors: 501006 and 501007 gave identical tables, an invented 999999 was accepted and gave the
same values). The version in a file name is therefore the version that was asked for, and not
proof of what the server calculated. `scripts/compare_hbefa_api.py` checks for changed values.
"""

import json
import os
import re
import time
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from dotenv import dotenv_values

from drive.config import HbefaApi, HbefaIngest, HbefaTable
from drive.io import hbefa

_HTTP_TIMEOUT = 120  # seconds, for one HTTP call; a whole job is limited by api.timeout_minutes
_REPORT_SECONDS = 60
# Jobs of large tables run for a long time, so a short outage while waiting must not lose the job
_MAX_POLL_FAILURES = 20  # in a row
_RETRY_SECONDS = 30


class HbefaApiError(RuntimeError):
    """The server refused a request or returned something unusable."""


def read_credentials(api: HbefaApi) -> tuple[str, str]:
    """E-mail and password by the names in the config: environment first, then `api.env_file`."""
    file = dotenv_values(api.env_file) if api.env_file is not None else {}
    values = {name: os.environ.get(name) or file.get(name) for name in (api.email_env, api.password_env)}
    email, password = values[api.email_env], values[api.password_env]
    if not email or not password:
        missing = [name for name, value in values.items() if not value]
        raise ValueError(f'HBEFA credentials {missing} are neither in the environment nor in {api.env_file}')
    return email, password


def login(api: HbefaApi) -> requests.Session:
    """Opens a logged-in session. A failed login also answers 200, but stays on the login page."""
    email, password = read_credentials(api)
    session = requests.Session()
    url = f'{api.base_url}/login'
    page = session.get(url, timeout=_HTTP_TIMEOUT)
    page.raise_for_status()
    token = re.search(r'id="csrf_token" name="csrf_token".*?value="(.*?)"', page.text)
    if token is None:
        raise HbefaApiError(f'No CSRF token on {url}, the login page has changed')
    response = session.post(url,
                            data={'email': email, 'password': password, 'csrf_token': token.group(1), 'submit': 'Login'},
                            headers={'X-CSRFToken': token.group(1), 'Referer': url},
                            timeout=_HTTP_TIMEOUT)
    response.raise_for_status()
    if urlparse(response.url).path == '/login':
        raise HbefaApiError(f'Login to {api.base_url} failed, check {api.email_env} and {api.password_env}')
    return session


def fetch_table(session: requests.Session, api: HbefaApi, payload: dict[str, str]) -> tuple[pd.DataFrame, dict]:
    """Submits one job and waits for its result.

    Returns:
        the table as the server sends it, and what the server reports about the job

    While waiting, connection errors and 5xx answers are retried, and an expired session is renewed.

    Raises:
        HbefaApiError: if the job is refused, fails, or takes longer than `api.timeout_minutes`
    """
    submitted = session.post(f'{api.base_url}/efa-async', json=payload, timeout=_HTTP_TIMEOUT)
    if submitted.status_code != 202:
        raise HbefaApiError(f'Job refused with status {submitted.status_code}: {submitted.text[:500]}')
    task_id = submitted.json()['task_id']

    url = f'{api.base_url}/efa-async/{task_id}'
    start = last_report = time.monotonic()
    failures = 0
    problem: str | None = None  # why the last poll failed
    while True:
        now = time.monotonic()
        if now - start > api.timeout_minutes * 60:
            raise HbefaApiError(f'Job {task_id} not finished after {api.timeout_minutes} minutes')
        try:
            if problem is not None and problem.endswith('401'):
                session = login(api)
            result = session.get(url, timeout=_HTTP_TIMEOUT)
            problem = f'status {result.status_code}' if result.status_code == 401 or result.status_code >= 500 else None
        except requests.RequestException as error:
            problem = type(error).__name__
        if problem is not None:
            failures += 1
            if failures > _MAX_POLL_FAILURES:
                raise HbefaApiError(f'Job {task_id}: gave up after {_MAX_POLL_FAILURES} failed polls, last {problem}')
            print(f'  job {task_id}: {problem}, retry {failures} of {_MAX_POLL_FAILURES}', flush=True)
            time.sleep(_RETRY_SECONDS)
            continue
        failures = 0
        if result.status_code == 200:
            break
        if result.status_code != 202:
            raise HbefaApiError(f'Job {task_id} failed with status {result.status_code}: {result.text[:500]}')
        if now - last_report > _REPORT_SECONDS:
            print(f'  {(now - start) / 60:.0f} min: {result.json().get("status", "")}', flush=True)
            last_report = now
        time.sleep(api.poll_seconds)

    body = result.json()
    if body.get('Input validation result') != 'OK' or body.get('errors') not in (None, 'None'):
        raise HbefaApiError(f'Job {task_id} failed: validation {body.get("Input validation result")!r}, '
                            f'errors {body.get("errors")!r}')
    if not body.get('Emission factors'):
        raise HbefaApiError(f'Job {task_id} returned no emission factors, only {sorted(body)}')
    report = {'input_parameters': json.loads(body['Input_pars']), 'warnings': body.get('Warnings')}
    return pd.read_json(StringIO(body['Emission factors'])), report


def build_payload(api: HbefaApi, table: HbefaTable, year: int, version: int) -> dict[str, str]:
    return {**api.request, **table.request, 'emcat': table.category, 'agglevel_ts': table.aggregation,
            'yearref': str(year), 'hbversion_int': str(version)}


def _save(raw: pd.DataFrame, file: hbefa.EfFile, payload: dict[str, str], report: dict) -> None:
    """Writes the table with a sidecar of the request. The rename makes a broken run leave no table."""
    file.path.parent.mkdir(parents=True, exist_ok=True)
    sidecar = {'downloaded_at': datetime.now(UTC).isoformat(), 'request': payload, **report}
    file.path.with_suffix('.request.json').write_text(json.dumps(sidecar, indent=2, ensure_ascii=False))
    partial = file.path.with_suffix('.parquet.partial')
    raw.to_parquet(partial, index=False)
    partial.replace(file.path)


def download_missing(config: HbefaIngest) -> list[Path]:
    """Downloads every table listed in `config.api.tables` that isn't in `config.directory` yet.

    Each table is checked against the EMISSION_FACTORS contract before it is saved.

    Returns:
        the paths of the new files
    """
    api = config.api
    if api is None:
        raise ValueError('No ingest.hbefa.api section in the config')
    new = []
    for table in api.tables:
        for year in table.years:
            name = hbefa.file_name(year, table.category, table.aggregation, config.version)
            file = hbefa.parse_file_name(config.directory / name)
            if file.path.exists():
                continue
            print(f'{name}: requesting', flush=True)
            start = time.monotonic()
            payload = build_payload(api, table, year, config.version)
            # a new session per table: jobs can run long enough for a session to expire
            raw, report = fetch_table(login(api), api, payload)

            echoed = report['input_parameters'].get('hbversion_int')
            if str(echoed) != str(config.version):
                raise HbefaApiError(f'{name}: asked for version {config.version}, the server reports {echoed}')
            rows = hbefa.to_contract(raw, file)
            _save(raw, file, payload, report)
            new.append(file.path)

            absent = sorted(set(payload['pollutant'].split(',')) - set(rows['pollutant']))
            print(f'{name}: {len(rows)} rows in {time.monotonic() - start:.0f} s'
                  + (f', no factors for {absent}' if absent else ''), flush=True)
            if report['warnings'] not in (None, 'None'):
                warnings = report['warnings']  # one entry per split of a large job, so many repeats
                for warning in sorted(set(warnings)) if isinstance(warnings, list) else [warnings]:
                    print(f'  server warning: {warning}')
    return new
