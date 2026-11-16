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


class LhmIngest(_Strict):
    """LHM detector exports and matched locations, see io.lhm."""
    directory: Path  # folder with the exports
    pattern: str = '*_MST_Detektoren*.csv'
    locations: Path  # matched detectors (DETEKTOR_ID, road_link_id)


class BastIngest(_Strict):
    """BASt counting stations, see io.bast and docs/bast_counts_README.md."""
    directory: Path  # downloads: annual/zst<station>_<year>.zip and raw/DZ_<year>[_<month>]_Rohdaten.zip
    locations: Path  # matched detectors (MST_ID, DETEKTOR_ID, road_link_id); its stations are downloaded
    years: tuple[int, int]  # first and last year (inclusive)
    annual_url: str  # with {year} and {station}
    page_url: str  # page that lists the raw-data archives
    raw_from: int  # raw archives from this year on (all stations, unchecked), annual files before (checked, BASt has
    # raw archives from 2021)
    refresh_months: int = 3  # raw archives whose period ended less than this many months ago are downloaded again


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


class MeteoIngest(_Strict):
    """DWD hourly temperatures, see io.dwd. Each ingest adds only the hours that are new or changed."""
    stations: list[str]  # DWD station ids, e.g. '03379'
    years: tuple[int, int]  # first and last year (inclusive), padded by a day for the conversion to local time


class BoundariesIngest(_Strict):
    """BKG VG250, see io.boundaries. Each download is kept as <directory>/vg250_<status date>.zip."""
    url: str
    directory: Path
    levels: list[str] = ['lan', 'krs', 'gem']


class IngestConfig(_Strict):
    lhm: LhmIngest | None = None
    bast: BastIngest | None = None
    hbefa: HbefaIngest | None = None
    calendar: CalendarIngest | None = None
    meteo: MeteoIngest | None = None
    boundaries: BoundariesIngest | None = None


class TemperatureConfig(_Strict):
    """Ambient temperature of a run, see domain.meteo."""
    station: str
    backup_station: str | None = None  # fills hours missing at `station`
    max_gap_hours: int = 6  # longest gap that is interpolated; a longer one raises
    timezone: str = 'Europe/Berlin'  # local time of counts and profiles


class RunConfig(_Strict):
    traffic_model: TrafficModel
    start: date | None = None  # first and last day of the emission calculation, one calendar year for now
    end: date | None = None
    reference_year: int  # normalisation year of the scaling, must match the traffic model year
    reference_day_type: Literal[0] = 0  # normal weekday, the only class that is a subset of its profile group
    data_version: int | datetime | None = None  # store batch id or tz-aware timestamp, None = latest
    hbefa_version: int | None = None  # the emission factors a run reads from the store
    vehicle_classes: list[str] = []
    components: list[str] = []
    # hot factors: the ambient pattern of each hour's temperature (R33, D32), or one fixed pattern (v1: T+25°C)
    hot_ambient: Literal['hourly_temperature', 'fixed'] = 'fixed'
    hot_ambient_pattern: str | None = None  # the pattern with hot_ambient: fixed
    hot_mode: Literal['los_specific', 'aggregated'] = 'los_specific'  # traffic situation per link and hour, or one mean
    area_type: Literal['Urban', 'Motorway', 'Rural'] = 'Urban'
    temperature: TemperatureConfig | None = None  # needed for cold starts
    clip_ags: str | None = None  # region (VG250 land area) the links are clipped to; None = no clipping


class ColdStartConfig(_Strict):
    """Settings of domain.cold_start (values from v1 notebook 11)."""
    vehicle_classes: list[str]  # classes with start factors and starts per zone
    road_types: list[str]  # links that receive starts; others are assumed to carry hot traffic only
    buffer_m: float  # starts of a zone go to the links within this distance
    components: list[str]  # start tables have no non-exhaust part, and 2024/2025 lack PM2.5-ex
    profile_road_type: str  # scaling road type whose hourly activity gives the starts per hour
    # vehicle_specific: daily scaling x share / reference share x diurnal cycle of the class (R40), so a reference
    # day gives about 1 per class, as for hot volumes; v1_share: v1's daily scaling x share x diurnal cycle
    start_scaling: Literal['vehicle_specific', 'v1_share'] = 'vehicle_specific'


class KernelConfig(_Strict):
    """Settings of domain.kernel (values from v1 hbefa_hot_emissions)."""
    vcr_thresholds: dict[str, tuple[float, float, float, float]]  # road type -> LOS limits of the VCR
    car_unit_factors: dict[str, float]  # HBS 2015


class CountsQAConfig(_Strict):
    """Settings of domain.counts_qa (defaults from v1 data_preprocessing/31)."""
    period_start: date
    period_end: date
    counter_link_overrides: Path | None = None  # corrections of the detector -> link matching (R26), see io.counter_links
    hourly_daily_tolerance: float = 0.025
    min_daily_value: float = 1.0
    outlier_z_threshold: float = 3.5
    sqv_f: float = 10000.0
    sqv_threshold: float = 0.6
    completeness_threshold: float = 0.8  # share of the days of the reference year and of the scaling year (R46)
    iqr_range: tuple[float, float] = (2.5, 97.5)
    # incomplete link-days (R41): hours with these flags count as missing; drop link-days with a missing hour or detector.
    # Defaults reproduce v1 (flags ignored, missing values summed as 0)
    missing_flags: list[str] = []
    drop_incomplete_days: bool = False
    # implausible class shares per link and year (R44): classes to check, robust z of the log annual share within
    # scaling road type and year; [] skips the check (v1)
    share_check_classes: list[str] = []
    share_z_threshold: float = 3.5
    share_min_days: int = 30
    share_min_links: int = 5


class GridConfig(_Strict):
    """An output grid (spec R12b): polygon cells with an id column, in any CRS."""
    path: Path  # relative to paths.data_root
    cell_id: str = 'locationcode'


class OutputsConfig(_Strict):
    grids: dict[str, GridConfig] = {}  # name -> grid; every run writes grid_<name>_<stem>.gpkg


class SharePool(_Strict):
    """Vehicle classes whose share is computed over several scaling road types together (spec D30)."""
    vehicle_classes: list[str]
    scaling_road_types: list[str]


class DriveConfig(_Strict):
    paths: PathsConfig
    traffic_models: dict[TrafficModel, TrafficModelConfig] = {}
    visum: VisumConfig | None = None
    ingest: IngestConfig = IngestConfig()
    run: RunConfig | None = None
    counts_qa: CountsQAConfig | None = None
    kernel: KernelConfig | None = None
    cold_start: ColdStartConfig | None = None
    scaling_road_types: dict[str, str] = {}  # road type -> scaling road type, unlisted types map to themselves
    # required with a run section, so that pooling is always stated: [] computes every share per road type
    vehicle_share_pools: list[SharePool] | None = None
    outputs: OutputsConfig = OutputsConfig()

    @model_validator(mode='after')
    def _check_and_resolve(self) -> 'DriveConfig':
        if self.run is not None and self.vehicle_share_pools is None:
            raise ValueError('vehicle_share_pools must be stated in a config with a run section ([] for no pooling)')
        root = self.paths.data_root
        if not root.is_absolute():
            raise ValueError('paths.data_root must be resolved before validation, use load_config()')
        bad = [m for m in self.traffic_models if not re.fullmatch(r'visum\d{4}', m)]
        if bad:
            raise ValueError(f'traffic model names must look like visum<year>, got {bad}')
        if self.run is not None and self.run.traffic_model not in self.traffic_models:
            raise ValueError(f'run.traffic_model {self.run.traffic_model} is not in traffic_models')
        self.paths.store = root / self.paths.store
        self.paths.results = root / self.paths.results
        for grid in self.outputs.grids.values():
            grid.path = root / grid.path
        if self.counts_qa is not None and self.counts_qa.counter_link_overrides is not None:
            self.counts_qa.counter_link_overrides = (root / self.counts_qa.counter_link_overrides).resolve()
        for m in self.traffic_models.values():
            m.links = root / m.links
            m.zones = root / m.zones
        if self.ingest.bast is not None:
            self.ingest.bast.directory = root / self.ingest.bast.directory
            self.ingest.bast.locations = root / self.ingest.bast.locations
        if self.ingest.lhm is not None:
            self.ingest.lhm.directory = root / self.ingest.lhm.directory
            self.ingest.lhm.locations = root / self.ingest.lhm.locations
        if self.ingest.hbefa is not None:
            self.ingest.hbefa.directory = root / self.ingest.hbefa.directory
            api = self.ingest.hbefa.api
            if api is not None and api.env_file is not None:
                api.env_file = root / api.env_file
        if self.ingest.boundaries is not None:
            self.ingest.boundaries.directory = root / self.ingest.boundaries.directory
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
