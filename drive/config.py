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
    calendar: Path = Path('auxiliary/calender_18to26.xlsx')  # v1's workbook, only read for comparisons with v1
    clip_boundary: Path | None = None  # interim: read directly until `drive ingest boundaries` exists
    results: Path = Path('inventory/v2')


class TrafficModelConfig(_Strict):
    links: Path  # raw VISUM link export
    zones: Path  # raw VISUM zone export
    crs: str  # expected CRS of both files, e.g. EPSG:25832; ingest raises on a mismatch
    link_columns: dict[str, str] = {}  # raw name -> standard VISUM name, for exports with other names
    zone_columns: dict[str, Literal['PC_starts', 'LCV_starts', 'HGV_starts']]  # raw name -> contract name


class RoadTypeRule(_Strict):
    """VISUM TYPENO range (inclusive) -> HBEFA road type, optionally only from a free-flow speed on."""
    typeno: tuple[int, int]
    road_type: str
    min_speed: int | None = None


class VisumConfig(_Strict):
    """Conversion of a VISUM export to the links contract, see io.visum."""
    min_dtv: float  # links with less daily traffic are dropped
    road_types: list[RoadTypeRule]  # the first matching rule wins
    excluded_typeno: list[tuple[int, int]]  # ranges without road traffic; any other unmatched TYPENO raises


class CountsSource(_Strict):
    """One preprocessed counting data file (detector -> road_link_id matching included)."""
    source: Literal['BASt', 'LHM']
    path: Path


class HbefaTable(_Strict):
    """Tables to download, one per year."""
    category: Literal['hot', 'start']
    aggregation: Literal['single_ts', 'aggregate_ts']
    years: list[int]
    request: dict[str, str] = {}  # HBEFA API parameters of these tables, on top of HbefaApi.request


class HbefaApi(_Strict):
    """HBEFA web API, see io.hbefa_api. Credentials are named here, their values are never in the config."""
    base_url: str
    email_env: str = 'HBEFA_EMAIL'
    password_env: str = 'HBEFA_PASSWORD'
    env_file: Path | None = None  # used for names that aren't in the environment
    poll_seconds: float = 5
    timeout_minutes: float = 120  # per table
    request: dict[str, str]  # HBEFA API parameters of all tables
    tables: list[HbefaTable]

    @model_validator(mode='after')
    def _check_request(self) -> 'HbefaApi':
        for request in [self.request, *(t.request for t in self.tables)]:
            reserved = {'emcat', 'agglevel_ts', 'yearref', 'hbversion_int'} & set(request)
            if reserved:
                raise ValueError(f'{sorted(reserved)} follow from the table and the version, remove them from request')
        return self


class HbefaIngest(_Strict):
    """Directory with emission factor tables, see io.hbefa for the naming scheme."""
    directory: Path
    version: int  # e.g. 501007
    api: HbefaApi | None = None  # only needed for `drive ingest hbefa --download`


class CalendarIngest(_Strict):
    """Calendar generated from the `holidays` package, see io.calendar_holidays."""
    country: str  # e.g. DE
    subdivision: str  # e.g. BY
    years: tuple[int, int]  # first and last year (inclusive)
    public_categories: list[str] = ['public']  # categories of the package that count as holidays
    overrides: Path | None = None  # corrections of the school holidays: csv with date, school_holiday, reason


class IngestConfig(_Strict):
    counts: list[CountsSource] = []
    hbefa: HbefaIngest | None = None
    calendar: CalendarIngest | None = None


class RunConfig(_Strict):
    traffic_model: TrafficModel
    start: date | None = None  # first and last day of the emission calculation, one calendar year for now
    end: date | None = None
    reference_year: int  # normalisation year of the scaling, must match the traffic model year
    reference_day_type: Literal[0] = 0  # normal weekday, the only class that is a subset of its profile group
    calendar_source: Literal['store', 'v1_workbook'] = 'store'  # v1_workbook: v1's day types, for comparisons with v1
    data_version: int | datetime | None = None  # store batch id or tz-aware timestamp, None = latest
    hbefa_version: int | None = None  # the emission factors a run reads from the store
    vehicle_classes: list[str] = []
    components: list[str] = []
    hot_ambient_pattern: str | None = None  # the HBEFA pattern of the hot factors (R33: fixed for now)
    hot_mode: Literal['los_specific', 'aggregated'] = 'los_specific'  # traffic situation per link and hour, or one mean
    area_type: Literal['Urban', 'Motorway', 'Rural'] = 'Urban'


class KernelConfig(_Strict):
    """Settings of domain.kernel (values from v1 hbefa_hot_emissions)."""
    vcr_thresholds: dict[str, tuple[float, float, float, float]]  # road type -> LOS limits of the VCR
    car_unit_factors: dict[str, float]  # HBS 2015


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
    visum: VisumConfig | None = None
    ingest: IngestConfig = IngestConfig()
    run: RunConfig | None = None
    counts_qa: CountsQAConfig | None = None
    kernel: KernelConfig | None = None
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
        self.paths.results = root / self.paths.results
        if self.paths.clip_boundary is not None:
            self.paths.clip_boundary = root / self.paths.clip_boundary
        for m in self.traffic_models.values():
            m.links = root / m.links
            m.zones = root / m.zones
        for c in self.ingest.counts:
            c.path = root / c.path
        if self.ingest.hbefa is not None:
            self.ingest.hbefa.directory = root / self.ingest.hbefa.directory
            api = self.ingest.hbefa.api
            if api is not None and api.env_file is not None:
                api.env_file = root / api.env_file
        if self.ingest.calendar is not None and self.ingest.calendar.overrides is not None:
            self.ingest.calendar.overrides = root / self.ingest.calendar.overrides
        return self


def load_config(path: str | Path) -> DriveConfig:
    """Loads and validates a run configuration from a YAML file."""
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text()) or {}
    paths = raw.get('paths', {})
    if 'data_root' in paths:
        paths['data_root'] = (path.parent / paths['data_root']).resolve()
    return DriveConfig.model_validate(raw)
