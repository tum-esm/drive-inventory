"""Known-answer tests of the BASt raw reader, time conversion, calendar rules and cold-start patterns.

All data is invented. Each test targets a failure mode that would not raise on its own.
"""

import zipfile

import numpy as np
import pandas as pd
import pytest

from drive.domain.calendar import (
    NORM_WEEKDAY,
    SATURDAY,
    SUNDAY_HOLIDAY,
    VACATION_WEEKDAY,
    WEEKDAY,
    classify_days,
)
from drive.domain.cold_start import start_patterns
from drive.domain.meteo import to_local_hourly
from drive.io.bast import read_raw_archive

CLASSES = ['Mot', 'Pkw', 'Lfw', 'PmA', 'Bus', 'LoA', 'LmA', 'Sat', 'Son']


def _field(value: int, flag: str = '-') -> str:
    return f' {value:4d}{flag}'


def test_bast_raw_reader_sums_lanes_per_direction_and_keeps_the_worst_flag(tmp_path):
    """Station 9999, 8+1 classes, two lanes in direction I and one in direction II, one hour on 4 March 2025.

    Lane counts (Mot, Pkw, Lfw, PmA, Bus, LoA, LmA, Sat, Son):
        lane 1 (I):  1, 70, 10, 1, 1, 3, 5, 7, 2 = 100
        lane 2 (I):  0, 40,  5, 0, 0, 2, 4, 9, 0 =  60, Sat flagged 's' (estimate)
        lane 3 (II): 2, 50,  8, 1, 1, 1, 1, 1, 0 =  65
    Direction I: PC = Pkw + PmA = 111, LCV = 15, HGV = LoA + LmA + Sat = 30 with the worst flag 's'.
    A record inserted at the clock change (status 'i') follows and must be skipped.
    Catches lanes assigned to the wrong direction, Sat counted twice (Lzg = LmA + Sat), a lost flag
    and an inserted record read as data.
    """
    lanes = [([1, 70, 10, 1, 1, 3, 5, 7, 2], ['-'] * 9),
             ([0, 40, 5, 0, 0, 2, 4, 9, 0], ['-'] * 7 + ['s', '-']),
             ([2, 50, 8, 1, 1, 1, 1, 1, 0], ['-'] * 9)]
    groups = ''.join(_field(sum(v)) + _field(v[5] + v[6] + v[7] + v[4]) for v, _ in lanes)  # KFZ, SV per lane
    classes = ''.join(_field(x, f) for v, flags in lanes for x, f in zip(v, flags))
    text = '\n'.join([
        'H00019999 09 A 00099 Teststation                V2.0',
        'R02 01 Nord N Sued S',
        'S02 09 KFZ SV  ' + ' '.join(CLASSES) + ';',
        '250304 01:00' + groups + classes,
        '250304i02:00' + ''.join(_field(0) for _ in range(6 + 27)),
    ]) + '\n'
    archive = tmp_path / 'DZ_2025_03_Rohdaten.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('BY9999.253', text.encode('ISO-8859-1'))

    counts, _ = read_raw_archive(archive)

    row = counts.set_index(['detector_id', 'vehicle_class'])
    assert row.loc[('99991', 'PC'), 'h00'] == 111
    assert row.loc[('99991', 'LCV'), 'h00'] == 15
    assert row.loc[('99991', 'HGV'), 'h00'] == 30
    assert row.loc[('99991', 'HGV'), 'flags'][0] == 's'
    assert row.loc[('99992', 'SUM'), 'h00'] == 65
    assert row.loc[('99992', 'HGV'), 'h00'] == 3
    # the other hours of the day have no record: missing ('a'), not 0
    assert np.isnan(row.loc[('99991', 'SUM'), 'h01']) and row.loc[('99991', 'SUM'), 'flags'][1] == 'a'


def test_utc_temperatures_become_local_wall_clock_hours_around_the_dst_change():
    """End of DST, 26 October 2025: 02:00-03:00 local exists twice (00:00 and 01:00 UTC).

    The UTC series is its hour number (22 on 25 October 22:00 UTC, ...). Local 01:00 is 23:00 UTC (CEST, +2),
    local 02:00 the mean of 00:00 and 01:00 UTC, local 03:00 is 02:00 UTC (CET, +1).
    Catches a missing or doubled time zone shift, which put v1's cold starts on the wrong hours (R1).
    """
    utc = pd.date_range('2025-10-25 20:00', '2025-10-26 06:00', freq='1h', tz='UTC')
    temperature = pd.Series(np.arange(len(utc), dtype=float) + 20, index=utc)  # 20 at 20:00 UTC, ...
    local = pd.date_range('2025-10-26 00:00', '2025-10-26 04:00', freq='1h')

    result, interpolated = to_local_hourly(temperature, local, 'Europe/Berlin', max_gap_hours=6)

    assert result.to_dict() == pytest.approx({local[0]: 22.0, local[1]: 23.0, local[2]: 24.5,
                                              local[3]: 26.0, local[4]: 27.0})
    assert interpolated == 0


def test_day_types_follow_the_priority_of_the_calendar_rules():
    """Public holiday before Saturday before vacation before normal weekday (docs/day_grouping_README.md).

    A Tuesday holiday inside the school vacation is Sunday/holiday, a vacation Saturday is Saturday,
    a vacation Tuesday is a vacation weekday, a normal Wednesday a normal weekday, Monday and Friday weekdays.
    Catches a changed rule order, which would silently move days between scaling references.
    """
    day_of_week = np.array([1, 5, 1, 2, 0, 4, 6])
    public = np.array([True, False, False, False, False, False, False])
    school = np.array([True, True, True, False, False, False, False])

    assert classify_days(day_of_week, public, school).tolist() == \
        [SUNDAY_HOLIDAY, SATURDAY, VACATION_WEEKDAY, NORM_WEEKDAY, WEEKDAY, WEEKDAY, SUNDAY_HOLIDAY]


def test_cold_start_and_hot_ambient_patterns_take_the_nearest_bin_ties_to_the_lower_one():
    """-12 -> -10 (outermost), -7.5 -> -10 (tie), 2.4 -> 0, 2.5 -> 0 (tie), 7.6 -> 10, 26 -> 25; NaN raises.

    Catches a shifted bin and NaN temperatures turned into -10 °C silently (v1).
    """
    patterns = start_patterns(np.array([-12, -7.5, 2.4, 2.5, 7.6, 26]))
    assert [p.split('°')[0] for p in patterns] == ['T-10', 'T-10', 'T+0', 'T+0', 'T+10', 'T+25']
    with pytest.raises(ValueError):
        start_patterns(np.array([5.0, np.nan]))
