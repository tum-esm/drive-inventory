"""Data contracts at stage boundaries (spec §3, principle 3).

Times: `date` is a local calendar day (Europe/Berlin for Munich) and `h00`..`h23` are
local wall-clock hours, as delivered by the counting data providers. DST days are not
corrected here (24 columns per day).
"""

import pandera.pandas as pa

HOURS = [f'h{h:02d}' for h in range(24)]
COUNT_SOURCES = ['BASt', 'LHM']
# VKFZ is the LHM speed of all vehicles (metric 'speed' only)
COUNT_VEHICLE_CLASSES = ['PC', 'LCV', 'HGV', 'MOT', 'BUS', 'SUM', 'VKFZ']
COUNT_KEY = ['source', 'detector_id', 'date', 'vehicle_class', 'metric']

_non_negative = pa.Check.ge(0)

RAW_COUNTS = pa.DataFrameSchema(
    {
        'source': pa.Column(str, pa.Check.isin(COUNT_SOURCES)),
        'detector_id': pa.Column(str),
        'detector_type': pa.Column(str, nullable=True),
        'date': pa.Column('datetime64[us]',
                          pa.Check(lambda s: s == s.dt.normalize(), error='date must be a whole day')),
        'vehicle_class': pa.Column(str, pa.Check.isin(COUNT_VEHICLE_CLASSES)),
        'metric': pa.Column(str, pa.Check.isin(['volume', 'speed'])),
        'daily_value': pa.Column(float, _non_negative, nullable=True),
        **{h: pa.Column(float, _non_negative, nullable=True) for h in HOURS},
    },
    checks=pa.Check(lambda df: (df['vehicle_class'] != 'VKFZ') | (df['metric'] == 'speed'),
                    error='VKFZ is only valid with metric speed'),
    unique=COUNT_KEY,
    strict=True,
    ordered=True,
    coerce=True,
)

LINK_VEHICLE_CLASSES = ['PC', 'LCV', 'HGV', 'MOT', 'BUS', 'SUM']

# Quality-controlled daily volumes per road link (output of domain.counts_qa)
LINK_COUNTS = pa.DataFrameSchema(
    {
        'road_link_id': pa.Column('int64'),
        'vehicle_class': pa.Column(str, pa.Check.isin(LINK_VEHICLE_CLASSES)),
        'date': pa.Column('datetime64[us]'),
        'road_type': pa.Column(str),
        'scaling_road_type': pa.Column(str),
        'day_type': pa.Column('int64', pa.Check.isin([0, 1, 2, 3, 4])),
        'sqv': pa.Column(float, pa.Check.in_range(0, 1), nullable=True),
        'valid': pa.Column(bool),
        'completeness': pa.Column(float, pa.Check.in_range(0, 1)),
        'complete': pa.Column(bool),
        'daily_value': pa.Column(float, pa.Check.gt(0)),
        **{h: pa.Column(float, _non_negative) for h in HOURS},
    },
    unique=['road_link_id', 'vehicle_class', 'date'],
    strict=True,
    ordered=True,
    coerce=True,
)

EF_KEY = ['hbefa_version', 'reference_year', 'emission_category', 'aggregation', 'pollutant', 'process_scope',
          'vehicle_class', 'traffic_situation', 'gradient', 'ambient_pattern']

# HBEFA emission factors, one row per key. `efa` is fleet-weighted, in `ef_unit` (cold-start
# excess factors can be negative). Start tables have no traffic situation, only single_ts
# tables have a gradient, and only the 2019 and 2020 tables have a process scope (TTW, WTT).
EMISSION_FACTORS = pa.DataFrameSchema(
    {
        'hbefa_version': pa.Column('int64'),
        'reference_year': pa.Column('int64'),
        'emission_category': pa.Column(str, pa.Check.isin(['hot', 'start'])),
        'aggregation': pa.Column(str, pa.Check.isin(['single_ts', 'aggregate_ts'])),
        'pollutant': pa.Column(str),
        'process_scope': pa.Column(str, nullable=True),
        'vehicle_class': pa.Column(str, pa.Check.isin(['PC', 'LCV', 'HGV', 'MOT', 'BUS'])),
        'traffic_situation': pa.Column(str, nullable=True),
        'gradient': pa.Column(str, nullable=True),
        'ambient_pattern': pa.Column(str),
        'road_category': pa.Column(str),
        'ef_unit': pa.Column(str, pa.Check.isin(['g/vehkm', 'g/start'])),
        'weight': pa.Column(float),
        'efa': pa.Column(float),
        'efa_0': pa.Column(float, nullable=True),
        'efa_100': pa.Column(float, nullable=True),
        'speed': pa.Column(float),
        'speed_0': pa.Column(float, nullable=True),
        'speed_100': pa.Column(float, nullable=True),
        'cum_mileage': pa.Column(float, nullable=True),
        'traffic_scenario': pa.Column(str),
        'country': pa.Column(str),
    },
    unique=EF_KEY,
    strict=True,
    ordered=True,
    coerce=True,
)

COUNTER_LINKS = pa.DataFrameSchema(
    {
        'source': pa.Column(str, pa.Check.isin(COUNT_SOURCES)),
        'detector_id': pa.Column(str),
        'traffic_model': pa.Column(str, pa.Check.str_matches(r'^visum\d{4}$')),
        'road_link_id': pa.Column('int64'),
    },
    unique=['source', 'detector_id', 'traffic_model'],
    strict=True,
    ordered=True,
    coerce=True,
)

HBEFA_ROAD_TYPES = ['Motorway-Nat', 'Motorway-City', 'TrunkRoad/Primary-National', 'TrunkRoad/Primary-City',
                    'Distributor/Secondary', 'Local/Collector', 'Access-residential']
HBEFA_GRADIENTS = ['-6%', '-4%', '-2%', '0%', '+2%', '+4%', '+6%']


def _is_wkb(s):
    return s.map(lambda g: isinstance(g, (bytes, bytearray)) and len(g) > 0)


# Speeds with HBEFA traffic situations per road type, ascending
HBEFA_SPEEDS = {'Motorway-Nat': [80, 90, 100, 110, 120, 130],
                'Motorway-City': [60, 70, 80, 90, 100, 110],
                'TrunkRoad/Primary-National': [70, 80, 90, 100, 110, 120],
                'TrunkRoad/Primary-City': [50, 60, 70, 80, 90],
                'Distributor/Secondary': [30, 40, 50, 60, 70, 80],
                'Local/Collector': [30, 40, 50, 60],
                'Access-residential': [30, 40, 50]}

# One row per directed link of a traffic model: `road_link_id` plus `from_node` identifies it,
# most ids have one row per direction. `file_row` keeps the order of the export. Geometry is
# WKB in the CRS of `crs`. `speed` is the model's free-flow speed (km/h), `dtv_*` are vehicles
# per average weekday, and `visum_length_km` is the model's length, not the geometry's.
LINKS = pa.DataFrameSchema(
    {
        'traffic_model': pa.Column(str, pa.Check.str_matches(r'^visum\d{4}$')),
        'road_link_id': pa.Column('int64'),
        'from_node': pa.Column('int64'),
        'to_node': pa.Column('int64'),
        'file_row': pa.Column('int64', pa.Check.ge(0)),
        'typeno': pa.Column('int64', pa.Check.ge(0)),
        'road_type': pa.Column(str, pa.Check.isin(HBEFA_ROAD_TYPES)),
        'scaling_road_type': pa.Column(str, pa.Check.isin(HBEFA_ROAD_TYPES)),
        'hour_capacity': pa.Column('int64', pa.Check.gt(0)),
        'lanes': pa.Column('int64', pa.Check.gt(0)),
        'hbefa_speed': pa.Column('int64', pa.Check.gt(0)),
        'speed': pa.Column('int64', pa.Check.gt(0)),
        'hbefa_gradient': pa.Column(str, pa.Check.isin(HBEFA_GRADIENTS)),
        'dtv_SUM': pa.Column(float, pa.Check.gt(0)),
        'dtv_PC': pa.Column(float, _non_negative),
        'dtv_LCV': pa.Column(float, _non_negative),
        'dtv_HGV': pa.Column(float, _non_negative),
        'visum_length_km': pa.Column(float, _non_negative),
        'crs': pa.Column(str),
        'geometry': pa.Column(object, pa.Check(_is_wkb, error='geometry must be WKB')),
    },
    unique=['traffic_model', 'road_link_id', 'from_node'],
    strict=True,
    ordered=True,
    coerce=True,
)

# One row per traffic zone with daily vehicle starts. HGV starts are optional per model.
ZONES = pa.DataFrameSchema(
    {
        'traffic_model': pa.Column(str, pa.Check.str_matches(r'^visum\d{4}$')),
        'zone_id': pa.Column('int64'),
        'file_row': pa.Column('int64', pa.Check.ge(0)),
        'PC_starts': pa.Column(float, _non_negative),
        'LCV_starts': pa.Column(float, _non_negative),
        'HGV_starts': pa.Column(float, _non_negative, nullable=True),
        'crs': pa.Column(str),
        'geometry': pa.Column(object, pa.Check(_is_wkb, error='geometry must be WKB')),
    },
    unique=['traffic_model', 'zone_id'],
    strict=True,
    ordered=True,
    coerce=True,
)

CALENDAR_KEY = ['region', 'date']

# One row per day. day_type: 0 normal weekday, 1 weekday, 2 vacation weekday, 3 Saturday, 4 Sunday/holiday, see domain.calendar.
# override: why school_holiday differs from the holiday package, empty if it does not
CALENDAR = pa.DataFrameSchema(
    {
        'region': pa.Column(str),
        'date': pa.Column('datetime64[us]'),
        'day_of_week': pa.Column('int64', pa.Check.in_range(0, 6)),
        'day_type': pa.Column('int64', pa.Check.isin([0, 1, 2, 3, 4])),
        'public_holiday': pa.Column(str, nullable=True),
        'school_holiday': pa.Column(str, nullable=True),
        'override': pa.Column(str, nullable=True),
    },
    unique=CALENDAR_KEY,
    strict=True,
    ordered=True,
    coerce=True,
)
