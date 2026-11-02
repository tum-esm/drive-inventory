"""Run configuration, loaded from YAML and validated with pydantic.

Relative paths are resolved as follows:
- `paths.data_root` relative to the directory of the config file
- every other path relative to `paths.data_root`
"""

import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

TrafficModel = str  # e.g. 'visum2019', 'visum2025'; link ids are only unique within one model


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PathsConfig(_Strict):
    data_root: Path
    store: Path = Path('restricted_input/drive.duckdb')
    calendar: Path = Path('auxiliary/calender_18to26.xlsx')


class TrafficModelConfig(_Strict):
    links: Path  # preprocessed VISUM links (visum_links_<year>.gpkg)


class CountsSource(_Strict):
    """One preprocessed counting data file (detector -> road_link_id matching included)."""
    source: Literal['BASt', 'LHM']
    path: Path


class IngestConfig(_Strict):
    counts: list[CountsSource] = []


class RunConfig(_Strict):
    traffic_model: TrafficModel
    reference_year: int  # normalisation year of the scaling, must match the traffic model year
    reference_day_type: int = 0  # normweekday
    data_version: int | datetime | None = None  # store batch id or tz-aware timestamp, None = latest


class CountsQAConfig(_Strict):
    """Settings of domain.counts_qa (defaults from v1 data_preprocessing/31)."""
    period_start: date
    period_end: date
    completeness_window: tuple[date, date]
    hourly_daily_tolerance: float = 0.025
    min_daily_value: float = 1.0
    outlier_z_threshold: float = 3.5
    sqv_f: float = 10000.0
    sqv_threshold: float = 0.6
    completeness_threshold: float = 0.6
    iqr_range: tuple[float, float] = (2.5, 97.5)


class DriveConfig(_Strict):
    paths: PathsConfig
    traffic_models: dict[TrafficModel, TrafficModelConfig] = {}
    ingest: IngestConfig = IngestConfig()
    run: RunConfig | None = None
    counts_qa: CountsQAConfig | None = None
    scaling_road_types: dict[str, str] = {}  # road type -> scaling road type, unlisted types map to themselves

    @model_validator(mode='after')
    def _check_and_resolve(self) -> 'DriveConfig':
        root = self.paths.data_root
        if not root.is_absolute():
            raise ValueError('paths.data_root must be resolved before validation, use load_config()')
        bad = [m for m in self.traffic_models if not re.fullmatch(r'visum\d{4}', m)]
        if bad:
            raise ValueError(f'traffic model names must look like visum<year>, got {bad}')
        if self.run is not None and self.run.traffic_model not in self.traffic_models:
            raise ValueError(f'run.traffic_model {self.run.traffic_model} is not in traffic_models')
        self.paths.store = root / self.paths.store
        self.paths.calendar = root / self.paths.calendar
        for m in self.traffic_models.values():
            m.links = root / m.links
        for c in self.ingest.counts:
            c.path = root / c.path
        return self


def load_config(path: str | Path) -> DriveConfig:
    """Loads and validates a run configuration from a YAML file."""
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text()) or {}
    paths = raw.get('paths', {})
    if 'data_root' in paths:
        paths['data_root'] = (path.parent / paths['data_root']).resolve()
    return DriveConfig.model_validate(raw)
