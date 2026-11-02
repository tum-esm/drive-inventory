"""Run configuration, loaded from YAML and validated with pydantic.

Relative paths are resolved as follows:
- `paths.data_root` relative to the directory of the config file
- every other path relative to `paths.data_root`
"""

import re
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


class TrafficModelConfig(_Strict):
    links: Path  # preprocessed VISUM links (visum_links_<year>.gpkg)


class CountsSource(_Strict):
    """One preprocessed counting data file (detector -> road_link_id matching included)."""
    source: Literal['BASt', 'LHM']
    path: Path


class IngestConfig(_Strict):
    counts: list[CountsSource] = []


class DriveConfig(_Strict):
    paths: PathsConfig
    traffic_models: dict[TrafficModel, TrafficModelConfig] = {}
    ingest: IngestConfig = IngestConfig()

    @model_validator(mode='after')
    def _check_and_resolve(self) -> 'DriveConfig':
        root = self.paths.data_root
        if not root.is_absolute():
            raise ValueError('paths.data_root must be resolved before validation, use load_config()')
        bad = [m for m in self.traffic_models if not re.fullmatch(r'visum\d{4}', m)]
        if bad:
            raise ValueError(f'traffic model names must look like visum<year>, got {bad}')
        self.paths.store = root / self.paths.store
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
