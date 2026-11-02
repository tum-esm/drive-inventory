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
