"""Run configuration, loaded from YAML and validated with pydantic.

Relative paths are resolved as follows:
- `paths.data_root` relative to the directory of the config file
- every other path relative to `paths.data_root`
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TrafficModel = str  # e.g. 'visum2019', 'visum2025'; link ids are only unique within one model


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PathsConfig(_Strict):
    data_root: Path
    store: Path = Path('restricted_input/drive.duckdb')


class CountsSource(_Strict):
    """One preprocessed counting data file and the traffic model its road_link_ids refer to."""
    source: Literal['BASt', 'LHM']
    path: Path
    traffic_model: TrafficModel = Field(pattern=r'^visum\d{4}$')


class IngestConfig(_Strict):
    counts: list[CountsSource] = []


class DriveConfig(_Strict):
    paths: PathsConfig
    ingest: IngestConfig = IngestConfig()

    @model_validator(mode='after')
    def _resolve_paths(self) -> 'DriveConfig':
        root = self.paths.data_root
        if not root.is_absolute():
            raise ValueError('paths.data_root must be resolved before validation, use load_config()')
        self.paths.store = root / self.paths.store
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
