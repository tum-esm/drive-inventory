"""Known-answer tests of the hot emission kernel. All numbers are invented, none come from HBEFA."""

import numpy as np
import pandas as pd
import pytest

from drive.domain.kernel import KernelParams, build_ef_table, daily_volumes, hot_emissions, profile_frame
from drive.schemas import HOURS

ROAD = 'Distributor/Secondary'
VEHICLES = ['PC', 'LCV', 'HGV']
COMPONENTS = ['CO2', 'NOx']

# Each factor is unique to its level of service, vehicle class and component, so that picking
# the wrong one changes the result. Factor = level of service x vehicle class x component.
LOS_FACTOR = {'Freeflow': 1.0, 'Heavy': 2.0, 'Satur.': 4.0, 'St+Go': 8.0, 'St+Go2': 16.0}
VEHICLE_FACTOR = {'PC': 1.0, 'LCV': 2.0, 'HGV': 10.0}
COMPONENT_FACTOR = {'CO2': 1.0, 'NOx': 0.5}


class OneDayActivity:
    """Stands in for domain.activity.Activity (see test_activity.py): the same values on every date."""

    road = pd.Index([ROAD])

    def get_daily_scaling_factors(self, date):
        return pd.Series([2.0], index=self.road)

    def get_vehicle_share(self, date):
        return pd.DataFrame({'PC': 0.75, 'LCV': 0.125, 'HGV': 0.125}, index=self.road)

    def get_hourly_scaling_factors(self, date):
        cycle = pd.Series(0.0, index=HOURS)
        cycle[['h07', 'h08', 'h10', 'h12', 'h14']] = [0.25, 0.375, 0.125, 0.125, 0.125]
        return pd.DataFrame({h: cycle[h] for h in HOURS}, index=VEHICLES)


def test_hot_emissions_match_a_hand_calculation():
    """One link on one day, worked out by hand.

    Volume: 800 vehicles x scaling 2 = 1600, so PC 1200, LCV 200, HGV 200.
    Car units per day: 1200 x 1 + 200 x 1 + 200 x 2 = 1800.
    Volume/capacity per hour with capacity 900: 1800 x hourly share / 900 = 2 x hourly share.

        hour  share  V/C   level of service
        h07   0.25   0.50  Freeflow: exactly on the limit 0.5, which still counts as below it
        h08   0.375  0.75  Satur.:   between the limits 0.7 and 0.9
        h10, h12, h14 0.125  0.25  Freeflow
        all others 0  0     Freeflow

    So 62.5 % of the traffic drives in Freeflow (factor 1) and 37.5 % in Satur. (factor 4):
        PC   CO2 = 1200 x (0.625 x 1 + 0.375 x 4) x 1  = 2550 g/km
        LCV  CO2 =  200 x (0.625 x 1 + 0.375 x 4) x 2  =  850 g/km
        HGV  CO2 =  200 x (0.625 x 1 + 0.375 x 4) x 10 = 4250 g/km
    NOx is half of that.

    Catches: the wrong factor for a level of service, vehicle class or component, the daily
    scaling or the hourly cycle getting lost, and `>` becoming `>=` at a limit (h07 would move
    to Heavy, and PC CO2 would become 2850). The hourly profile must add up to the same totals, which
    catches a profile cell that is written to the wrong hour, class or component.
    """
    links = pd.DataFrame({'dtv_SUM': [800.0], 'scaling_road_type': [ROAD], 'road_type': [ROAD],
                          'hbefa_speed': [50], 'hbefa_gradient': ['0%'], 'hour_capacity': [900]})
    corrections = pd.DataFrame({'hgv_corr': [1.0], 'lcv_corr': [1.0]})
    params = KernelParams(vehicle_classes=VEHICLES,
                          components=COMPONENTS,
                          car_unit_factors={'PC': 1.0, 'LCV': 1.0, 'HGV': 2.0},
                          vcr_thresholds={ROAD: (0.5, 0.7, 0.9, 1.0)})
    # the names are written out instead of using kernel.traffic_situation, to check that as well
    factors = pd.DataFrame([{'traffic_situation': f'URB/Distr/50/{los}', 'vehicle_class': vehicle, 'gradient': '0%',
                             'pollutant': component, 'efa': los_factor * vehicle_factor * component_factor}
                            for los, los_factor in LOS_FACTOR.items()
                            for vehicle, vehicle_factor in VEHICLE_FACTOR.items()
                            for component, component_factor in COMPONENT_FACTOR.items()])

    dates = pd.date_range('2025-01-07', periods=1)
    ef = build_ef_table(links, factors, params)
    result = hot_emissions(links, corrections, OneDayActivity(), dates, ef, params,
                           profile_weights={'length_km': np.array([1.0])})

    expected = {
        'PC_CO2': 2550.0, 'PC_NOx': 1275.0,
        'LCV_CO2': 850.0, 'LCV_NOx': 425.0,
        'HGV_CO2': 4250.0, 'HGV_NOx': 2125.0,
    }
    assert result.emissions.iloc[0].to_dict() == pytest.approx(expected)

    profile = profile_frame(result.profiles['length_km'], dates, ef, params)
    hourly_sum = profile.groupby(['vehicle_class', 'component'])['emission'].sum()
    assert {f'{v}_{c}': value for (v, c), value in hourly_sum.items()} == pytest.approx(expected)
    # only the five hours with traffic have emissions, h08 alone carries 37.5 % of them
    by_hour = profile.groupby(profile['time'].dt.hour)['emission'].sum()
    assert list(by_hour[by_hour > 0].index) == [7, 8, 10, 12, 14]
    assert by_hour[8] / by_hour.sum() == pytest.approx(0.375 * 4 / (0.625 + 0.375 * 4))


def test_vehicle_split_keeps_the_total():
    """HGV and LCV are corrected per link; PC, MOT and BUS share the factor k that keeps the total.

    1000 vehicles, counted shares PC 0.70, LCV 0.10, HGV 0.10, BUS 0.05, MOT 0.05,
    corrections HGV 2, LCV 0.5:
        HGV = 1000 x 0.10 x 2   = 200
        LCV = 1000 x 0.10 x 0.5 =  50
        k   = (1 - 0.2 - 0.05) / (1 - 0.1 - 0.1) = 0.9375
        PC  = 700 x k = 656.25, BUS = MOT = 50 x k = 46.875; total 1000

    Catches a wrong k, which would silently move traffic between vehicle classes.
    """
    vehicles = ['PC', 'LCV', 'HGV', 'BUS', 'MOT']
    shares = np.array([[0.70, 0.10, 0.10, 0.05, 0.05]])
    volumes = daily_volumes(np.array([1000.0]), shares, np.array([2.0]), np.array([0.5]), vehicles)

    assert dict(zip(vehicles, volumes[0])) == pytest.approx(
        {'PC': 656.25, 'LCV': 50.0, 'HGV': 200.0, 'BUS': 46.875, 'MOT': 46.875})
    assert volumes.sum() == pytest.approx(1000.0)
