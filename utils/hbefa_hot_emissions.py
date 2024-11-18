"""This module is used to import the emission factors from HBEFA exported *.csv files
and use them to calculate hourly traffic emissions of different vehicle classes and 
components.
"""
    
__version__ = 0.3
__author__ = "Daniel Kühbacher"

import pandas as pd
import numpy as np

from typing import Literal

from traffic_counts import TrafficCounts
import data_paths  

class HbefaHotEmissions:
    """Defines HBEFA parameters and classes, imports emission factors and 
    calculates hourly traffic emissions of different vehicle classes and components
    """
    
    _vehicle_classes = ['PC', 'LCV', 'HGV', 'BUS', 'MOT']
    
    _hbefa_raw_vehicle_classes = {'pass. car' : 'PC',
                                  'LCV': 'LCV',
                                  'HGV' : 'HGV',
                                  'motorcycle': 'MOT',
                                  'coach': 'BUS'}
    
    # all available components in HBEFA
    _all_components = ['NH3', 'HC', 'CO', 'NOx', 'FC', 'FC_MJ', 'PM', 'PN', 'CO2(rep)',
                       'CO2(total)', 'NO2', 'CH4', 'NMHC', 'Pb', 'SO2', 'N2O',
                       'PM (non-exhaust)', 'Benzene', 'PM2.5', 'BC (exhaust)',
                       'PM2.5 (non-exhaust)', 'BC (non-exhaust)', 'CO2e']
    
    # thresholds acquired from different sources and expert assessments
    # the values are optimized for Munichs urban traffic basend 
    # on national LOS distribution
    service_thresholds = {'Motorway-Nat': [0.5, 0.71, 0.98, 1.1],
                          'Motorway-City': [0.55, 0.75, 0.9, 1], # not used
                          'TrunkRoad/Primary-National': [0.33, 0.5, 0.7, 0.8],
                          'TrunkRoad/Primary-City': [0.67, 0.82, 0.92, 1.02],
                          'Distributor/Secondary': [0.37, 0.5, 0.63, 0.8],
                          'Local/Collector': [0.55, 0.75, 0.9, 1], # not used
                          'Access-residential': [0.14, 0.25, 0.39, 0.52]}
    
    # level-of-service classes in HBEFA
    _service_class = {0: 'Freeflow',
                     1: 'Heavy',
                     2: 'Satur.',
                     3: 'St+Go',
                     4: 'St+Go2'}
    
    _hbefa_raw_road_types = {'Motorway-Nat': 'MW-Nat.',
                             'Motorway-City': 'MW-City',
                             'TrunkRoad/Primary-National': 'Trunk-Nat.',
                             'TrunkRoad/Primary-City': 'Trunk-City',
                             'Distributor/Secondary': 'Distr',
                             'Local/Collector': 'Local',
                             'Access-residential': 'Access'}
    
    praeamble = {'Urban': 'URB',
                 'Motorway': 'MW', 
                 'Rural': 'RUR'}
    
    # multipliers to calculate the daily traffic volume as car units 
    # according to HBS 2015
    car_unit_factors = {'HGV': 2.5,
                        'BUS': 1.75,
                        'LCV': 1,
                        'PC': 1,
                        'MOT': 1}


    def __init__(self, 
                 components : list = ['CO2(rep)', 'NOx', 'CO'],
                 vehicle_classes : list = ['PC', 'LCV', 'HGV'], 
                 ef_type : Literal['EFA_weighted', 'EFA_WTT_weighted',
                                   'EFA_WTW_weighted'] = 'EFA_weighted',
                 area_type: Literal['Urban', 'Motorway', 'Rural'] = 'Urban'):
        """Imports emission factors from HBEFA-exported *.txt files and initializes 
        the class.

        Args:
            components (list, optional): Species to be considered in the calculation.
            Defaults to ['CO2(rep)', 'NOx', 'CO'].
            ef_type (Literal[EFA_weighted, EFA_WTT_weighted], optional): 
            Type of emission factor to be considered.
            Defaults to 'EFA_weighted'.
        """
        
        assert all([c in HbefaHotEmissions._all_components for c in components])
        assert all([v in HbefaHotEmissions._vehicle_classes for v in vehicle_classes])
        
        self.components = components
        self.vehicle_classes = vehicle_classes
        self.ef_type = ef_type
        self.area_type = area_type
    
        # load emission factors with explicit traffic situations
        self.ef_dict = self._import_hbefa_ef(data_paths.EF_TS, 
                                            columns_to_keep = ['VehCat', 'Year',
                                                               'Component', 'TrafficSit',
                                                               'Gradient', 'EFA_weighted',
                                                               'EFA_WTT_weighted', 
                                                               'EFA_WTW_weighted'], 
                                            index_cols = ['VehCat', 'Year', 'TrafficSit',
                                                          'Gradient','Component'])
        # load emission factors with aggregated traffic situations
        self.ef_aggregated = self._import_hbefa_ef(data_paths.EF_AGG,
                                                columns_to_keep= ['Year', 'Component',
                                                                  'VehCat', 'RoadCat',
                                                                  'EFA_weighted',
                                                                  'EFA_WTT_weighted', 
                                                                  'EFA_WTW_weighted'],
                                                index_cols = ['Year', 'RoadCat',
                                                              'VehCat','Component'])
  
      
    def _import_hbefa_ef(self,
                    filepath : str,
                    columns_to_keep : list,
                    index_cols : list) -> dict:
    
        """Import emission factors from HBEFA-exported *.csv table
        
        Args:
            filepath (str): path to emission factor table
            
        Returns:
            dict: emission factors
        """
        try:
            ef = pd.read_csv(filepath, sep=';', encoding='latin_1',
                             on_bad_lines= 'skip', decimal=',', 
                             dtype={'AmbientCondPattern': str}) 
            
            ef['VehCat']= ef['VehCat'].map(HbefaHotEmissions._hbefa_raw_vehicle_classes)
            ef= ef[columns_to_keep].set_index(index_cols) # reduce to useful columns
            ef_dict= ef.to_dict() # convert to dict for faster access
            print(f'Loaded emission factors from {filepath}')
            return ef_dict
        
        except Exception as e: 
            print(f'Could not load table from {filepath}\n')
            print(e)
            return None


    def calc_los_class(self, 
                       htv_car_unit:float,
                       hour_capacity:float, 
                       road_type:str, 
                       hbefa_speed:int) -> str:
        """Calculate traffic situation based on hourly volume capacity ratio

        Args:
            htv_car_unit (float): Hourly Traffic Volume in passenger car units (PCU)
            hour_capacity (float): road specific hourly capacity
            road_type (str): road type of the link
            hbefa_speed (int): Indicated speed converted to HBEFA speed

        Returns:
            str: HBEFA definition of the traffic situation
        """      
        praeamble  = HbefaHotEmissions.praeamble[self.area_type]
        vc_ratio = (htv_car_unit / hour_capacity) #hourly volume capacity ratio [%]

        iterator = 0 # used to access the right service class
        # calculate category based on treshold provided in "service_thresholds"
        for tres in HbefaHotEmissions.service_thresholds[road_type]:
            if vc_ratio <= tres:
                break
            iterator += 1
        
        los = f'{praeamble}/{HbefaHotEmissions._hbefa_raw_road_types[road_type]}/{str(hbefa_speed)}/{HbefaHotEmissions._service_class[iterator]}'
        return los
    
    
    def calculate_emissions_daily(self,
                                  mode: Literal['aggregated', 'los_specific'],
                                  dtv_vehicle:dict,
                                  diurnal_cycle_vehicle:pd.DataFrame,
                                  road_type:str,
                                  hbefa_gradient:str,
                                  hbefa_speed:float,
                                  hour_capacity:int,
                                  year:int) -> dict:
        """Calculate emissions for a full day and return daily values

        Args:
            mode (Literal['aggregated', 'los_specific']): if aggregated -> use aggregated EF
                                                          if los_specific -> use los specific EF
            dtv_vehicle (dict): vehicle-specific daily traffic volume
            diurnal_cycle_vehicle (pd.DataFrame): daily traffic cycle (24h) for different vehicle types
            road_type (str): Road type
            speed (int): Speed
            slope (float): Road gradient
            hour_capacity (int): Hourly capacity of the road
            year (int): year of investigation (there are different emission factors for different years)

        Returns:
            dict: calculated emission for each vehicle class, component and hour of the day.
        """
        
        # caclulate hourly traffic count of each vehicle class
        try:
            dtv_array = np.array([dtv_vehicle[v] for v in diurnal_cycle_vehicle.index])
            htv = (np.transpose(diurnal_cycle_vehicle.to_numpy()) * dtv_array)
        except KeyError as e:
            print('Keys in dtv_vehicle don`t agree with indexes in diurnal cycle.')
            print('Check key ' + str(e))
            return 0

        # calculate total hourly traffic count as passenger car equivalents
        htv_car_units = np.array([HbefaHotEmissions.car_unit_factors[v]\
            for v in diurnal_cycle_vehicle.index])
        
        # initialize emissions dictionary
        vehicle_component_tuples = [(v,c) for v in self.vehicle_classes
                                    for c in self.components] 
        emissions_dict = {_vc:0 for _vc in vehicle_component_tuples}
        
        
        if mode == 'los_specific':
            htv_car_units = (htv * htv_car_units).sum(axis=1)
            # list of 24 service classes for each hour of the day
            los_class = [self.calc_los_class(htv_car_unit = x,
                                            hour_capacity = hour_capacity,
                                            road_type = road_type,
                                            hbefa_speed = hbefa_speed) 
                        for x in htv_car_units]
            
            # calculate emissions for each hour of the day
            for i in range(0,24):
                # combine vehicle class and hourly traffic volume for each vehicle
                htv_hour = dict(zip(diurnal_cycle_vehicle.index, htv[i]))
                los_hour = los_class[i]
            
                # caclulate emissions for components and vehicle classes
                for v in self.vehicle_classes:
                    for c in self.components:
                        try:
                            emission = self.ef_dict[self.ef_type]\
                                    [v, year, los_hour, hbefa_gradient, c] * htv_hour[v]
                            emissions_dict[(v,c)] += emission
                        except Exception: # catch errors from missing gradinent values
                            try:
                                emission = self.ef_dict[self.ef_type]\
                                        [v, year, los_hour, '0%', c] * htv_hour[v]
                                emissions_dict[(v,c)] += emission
                            except Exception as e:
                                print(road_type, hbefa_gradient, hbefa_speed)
                                print('Exception ' + (str(e)))
                                return 0
                            
        elif mode == 'aggregated':
                    # calculate emissions for each hour of the day
            for i in range(0,24):
                # combine vehicle class and hourly traffic volume for each vehicle
                htv_hour = dict(zip(diurnal_cycle_vehicle.index, htv[i]))
                
                # caclulate emissions for components and vehicle classes
                for v in self.vehicle_classes:
                    for c in self.components:
                        emission = self.ef_aggregated[self.ef_type][year,
                                                                    self.area_type,
                                                                    v,
                                                                    c]* htv_hour[v]
                        emissions_dict[(v,c)] += emission
        
        return emissions_dict



    def calculate_emissions_hourly(self,
                                  dtv_vehicle:dict,
                                  diurnal_cycle_vehicle:pd.DataFrame,
                                  road_type:str,
                                  hbefa_gradient:str,
                                  hbefa_speed:float,
                                  hour_capacity:int,
                                  year:int) -> dict:
        """Calculate emissions for a full day and return hourly values   

        Args:
            dtv_vehicle (dict): vehicle-specific daily traffic volume
            diurnal_cycle_vehicle (pd.DataFrame): daily traffic cycle for different vehicle types
            road_type (str): Road type
            speed (int): Speed
            slope (float): Road gradient
            hour_capacity (int): Hourly capacity of the road
            year (int): year of investigation (EFs differ for different years)

        Returns:
            dict: calculated emission for each vehicle class, component and hour.
        """
        
        # caclulate hourly traffic count of each vehicle class
        try:
            dtv_array = np.array([dtv_vehicle[v] for v in diurnal_cycle_vehicle.index])
            htv = (np.transpose(diurnal_cycle_vehicle.to_numpy()) * dtv_array)
        except KeyError as e:
            print('Keys in dtv_vehicle don`t agree with indexes in diurnal cycle.')
            print('Check key ' + str(e))
            return 0

        # calculate total hourly traffic count as passenger car equivalents
        htv_car_units = np.array([HbefaHotEmissions.car_unit_factors[v]\
            for v in diurnal_cycle_vehicle.index])
        htv_car_units = (htv * htv_car_units).sum(axis=1)
        
        # list of 24 service classes for each hour of the day
        los_class = [self.calc_los_class(htv_car_unit = x,
                                         hour_capacity = hour_capacity,
                                         road_type = road_type,
                                         hbefa_speed = hbefa_speed) 
                     for x in htv_car_units]
        
        vehicle_component_hour_tuples = [(v,c,h) for v in self.vehicle_classes
                                         for c in self.components
                                         for h in range(0,24)]
        
        emissions_dict = {comb:0 for comb in vehicle_component_hour_tuples}
        
        # calculate emissions for each hour of the day
        for i in range(0,24):
            # combine vehicle class and hourly traffic volume for each vehicle
            htv_hour = dict(zip(diurnal_cycle_vehicle.index, htv[i]))
            los_hour = los_class[i]
        
            # caclulate emissions for components and vehicle classes
            for v in self.vehicle_classes:
                for c in self.components:
                    try:
                        emission = self.ef_dict[self.ef_type]\
                                [v, year, los_hour, hbefa_gradient, c] * htv_hour[v]
                        emissions_dict[(v,c,i)] = emission

                    except Exception: # catch errors from missing gradinent values
                        try: 
                            emission = self.ef_dict[self.ef_type]\
                                    [v, year, los_hour, '0%', c] * htv_hour[v]
                            emissions_dict[(v,c,i)] = emission
 
                        except Exception as e:
                            print(road_type, hbefa_gradient, hbefa_speed)
                            print('Exception ' + (str(e)))
                            return 0
        return emissions_dict



if __name__ == '__main__':
    """Example usage and test of the HBEFA hot emissions class.
    """

    # test the function
    dtv_vehicle_test = {'PC':10000, 
                    'LCV': 1500, 
                    'HGV': 1000,
                    'MOT': 100, 
                    'BUS': 50}
    
    cycles = TrafficCounts(init_timeprofile=False)
    diurnal_cycles = cycles.get_hourly_scaling_factors(date='2019-03-23')
    
    t = HbefaHotEmissions(components = ['CO2e'],
                          vehicle_classes= ['PC'],
                          )
    
    emissions = t.calculate_emissions_daily(
        mode = 'los_specific',
        dtv_vehicle = dtv_vehicle_test,
        hour_capacity = 1000,
        diurnal_cycle_vehicle = diurnal_cycles,
        road_type = 'Distributor/Secondary',
        hbefa_speed = 70,
        hbefa_gradient = '0%',
        year = 2019)
    
    print(emissions)