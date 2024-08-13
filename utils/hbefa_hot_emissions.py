"""This module is used to import the emission factors from HBEFA exported *.XLS tables
and use them to calculate hourly traffic emissions of different vehicle classes and components.
"""
    
__version__ = 0.2
__author__ = "Daniel Kühbacher"

import os

import pandas as pd
import numpy as np
import xlrd

from typing import Literal

from traffic_counts import TrafficCounts
import data_paths


class HbefaHotEmissions:
    """Defines HBEFA parameters and classes, imports emission factors and 
    calculates hourly traffic emissions of different vehicle classes and components
    """
    
    vehicle_classes = ['PC', 'LCV', 'HGV', 'BUS', 'MOT']
    
    hbefa_raw_vehicle_classes = {'PC': 'pass. car',
                                 'LCV': 'LCV',
                                 'HGV' : 'HGV',
                                 'MOT': 'motorcycle',
                                 'BUS': 'coach'}
    
    components = ['CO', 'NOx', 'PM', 'CO2(rep)', 'CO2(total)',
                  'NO2', 'CH4', 'BC (exhaust)', 'CO2e']
    
    # thresholds acquired from different sources and expert assessments
    # the secon value is irrelevant since it also results in "Heavy" traffic
    #'TrunkRoad/Primary-National': [0.25, 0.3, 0.38, 0.45],
    service_thresholds = {'Motorway-Nat': [0.5, 0.71, 0.98, 1.1], # optimized thresholds
                          'Motorway-City': [0.55, 0.75, 0.9, 1], # not used
                          'TrunkRoad/Primary-National': [0.33, 0.5, 0.7, 0.8], # optimized thresholds
                          'TrunkRoad/Primary-City': [0.67, 0.82, 0.92, 1.02], # optimized thresholds
                          'Distributor/Secondary': [0.37, 0.5, 0.63, 0.8], # optimized thresholds
                          'Local/Collector': [0.55, 0.75, 0.9, 1], # not used
                          'Access-residential': [0.14, 0.25, 0.39, 0.52]} # optimized thresholds
    
    # level-of-service classes in HBEFA
    service_class = {0: 'Freeflow',
                     1: 'Heavy',
                     2: 'Satur.',
                     3: 'St+Go',
                     4: 'St+Go2'}
    
    #assigns LOS classes to hbefa service classes
    los_hbefa_mapping = {'A': 'Freeflow', 
                         'B': 'Freeflow', 
                         'C': 'Heavy', 
                         'D': 'Heavy', 
                         'E': 'Satur.', 
                         'F': 'St+Go'}

    hbefa_road_abbreviations = {'Motorway-Nat': 'MW-Nat.',
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


    def __init__(self):
        """Import emission factors and save as dict
        """
        self.ef_dict = {}
        for vehicle in HbefaHotEmissions.vehicle_classes:
             value = self._import_hbefa_ef(
                 eval(f'data_paths.EF_{vehicle}'))
             self.ef_dict.update({vehicle:value})
             
        self.ef_aggregated = self._import_hbefa_ef(
            eval(f'data_paths.EF_aggregated_LOS'), 
            columns_to_keep = ["Year", "Component", "VehCat",
                               "RoadCat", "EFA_weighted"],
            index_cols = ['Year', 'RoadCat', 'VehCat','Component']
            )


    def _import_hbefa_ef(self,
                         filepath:str,
                         columns_to_keep:list = ['Year', 'Component', 'TrafficSit',
                                                 'Gradient', 'EFA_weighted'],
                         index_cols:list = ['Year', 'TrafficSit',
                                            'Gradient','Component']
                         ) -> dict:
        """Import emission factors from HBEFA-exported *.XLS table
        
        Args:
            filepath (str): path to emission factor table
            
        Returns:
            dict: emission factors
        """
        try:
            workbook = xlrd.open_workbook(filepath,
                                          logfile = open(os.devnull,"w"))
            df = pd.read_excel(workbook) # read_excel accepts workbooks too
            df = df[columns_to_keep].set_index(index_cols) # reduce to interesting columns
            df_dict = df.to_dict() # convert to dict for faster access
            print(f'Loaded emission factors from {filepath}')
            return df_dict
        
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
            htv_car_unit (float): Hourly Traffic Volume converted to passenger car equivalents
            hour_capacity (float): road specific hour capacity
            road_type (str): road type of the link
            hbefa_speed (int): Indicated speed converted to HBEFA speed

        Returns:
            str: HBEFA definition of the traffic situation
        """      
        praeamble  = "URB"
        vc_ratio = (htv_car_unit / hour_capacity) #hourly volume capacity ratio [%]

        iterator = 0 # used to access the right service class
        # calculate category based on treshold provided in "service_thresholds"
        for tres in HbefaHotEmissions.service_thresholds[road_type]:
            if vc_ratio <= tres:
                break
            iterator += 1
        
        los = f'{praeamble}/{HbefaHotEmissions.hbefa_road_abbreviations[road_type]}/\
            {str(hbefa_speed)}/{HbefaHotEmissions.service_class[iterator]}'
        return los
    
    
    def calculate_emissions_daily(self,
                                  mode:Literal['aggregated', 'los_specific'],
                                  dtv_vehicle:dict,
                                  diurnal_cycle_vehicle:pd.DataFrame,
                                  road_type:str,
                                  hbefa_gradient:str,
                                  hbefa_speed:float,
                                  hour_capacity:int,
                                  year:int) -> dict:
        """Calculate emissions for a full day and return daily values

        Args:
            mode (Literal['aggregated', 'los_specific']): if aggregated -> use aggregated emission factors
                                                          if los_specific -> use los specific emission factors
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
            print('The keys in dtv_vehicle do not agree with the indexes in the diurnal cycles dataframe.')
            print('Check key ' + str(e))
            return 0

        # calculate total hourly traffic count as passenger car equivalents
        htv_car_units = np.array([HbefaHotEmissions.car_unit_factors[v]\
            for v in diurnal_cycle_vehicle.index])
        
        # initialize emissions dictionary
        vehicle_component_tuples = [(v,c) for v in HbefaHotEmissions.vehicle_classes
                                    for c in HbefaHotEmissions.components] 
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
                for v in HbefaHotEmissions.vehicle_classes:
                    for c in HbefaHotEmissions.components:
                        try:
                            emission = self.ef_dict[v]['EFA_weighted']\
                                    [year, los_hour, hbefa_gradient, c] * htv_hour[v]
                            emissions_dict[(v,c)] += emission
                        except: # some gradient values are missing which could cause errors
                            try:
                                emission = self.ef_dict[v]['EFA_weighted']\
                                        [year, los_hour, '0%', c] * htv_hour[v]
                                emissions_dict[(v,c)] += emission
                            except Exception as e:
                                print(road_type)
                                print(hbefa_gradient)
                                print(hbefa_speed)
                                print('Exception ' + (str(e)))
                                print('Cannot calculate emissions.')
                                return 0
                            
        elif mode == 'aggregated':
                    # calculate emissions for each hour of the day
            for i in range(0,24):
                # combine vehicle class and hourly traffic volume for each vehicle
                htv_hour = dict(zip(diurnal_cycle_vehicle.index, htv[i]))
                
                # caclulate emissions for components and vehicle classes
                for v in HbefaHotEmissions.vehicle_classes:
                    for c in HbefaHotEmissions.components:
                        hbefa_raw_vehicle_class = HbefaHotEmissions.hbefa_raw_vehicle_classes[v]
                        emission = self.ef_aggregated['EFA_weighted'][year,
                                                                    'Urban',
                                                                    hbefa_raw_vehicle_class,
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
            print('The keys in dtv_vehicle do not agree with the indexes in the diurnal cycles dataframe.')
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
        
        vehicle_component_hour_tuples = [(v,c,h) for v in HbefaHotEmissions.vehicle_classes
                                         for c in HbefaHotEmissions.components
                                         for h in range(0,24)]
        
        emissions_dict = {comb:0 for comb in vehicle_component_hour_tuples}
        
        # calculate emissions for each hour of the day
        for i in range(0,24):
            # combine vehicle class and hourly traffic volume for each vehicle
            htv_hour = dict(zip(diurnal_cycle_vehicle.index, htv[i]))
            los_hour = los_class[i]
        
            # caclulate emissions for components and vehicle classes
            for v in HbefaHotEmissions.vehicle_classes:
                for c in HbefaHotEmissions.components:
                    try:
                        emission = self.ef_dict[v]['EFA_weighted']\
                                [year, los_hour, hbefa_gradient, c] * htv_hour[v]
                        emissions_dict[(v,c,i)] = emission

                    except: # some gradient values are missing which could cause errors
                        try: 
                            emission = self.ef_dict[v]['EFA_weighted']\
                                    [year, los_hour, '0%', c] * htv_hour[v]
                            emissions_dict[(v,c,i)] = emission
 
                        except Exception as e:
                            print(road_type)
                            print(hbefa_gradient)
                            print(hbefa_speed)
                            print('Exception ' + (str(e)))
                            print('Cannot calculate emissions.')
                            return 0
        return emissions_dict


if __name__ == '__main__':

    # test the function
    dtv_vehicle_test = {'PC':10000, 
                    'LCV': 1500, 
                    'HGV': 1000,
                    'MOT': 100, 
                    'BUS': 50}
    
    cycles = TrafficCounts(init_timeprofile=False)
    diurnal_cycles = cycles.get_hourly_scaling_factors(date='2019-03-23')
    
    t = HbefaHotEmissions()
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