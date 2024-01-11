"""This module is used to import the emission factors from HBEFA exported *.XLS tables
and use them to calculate hourly traffic emissions of different vehicle classes and components.
"""
    
__version__ = 0.1
__author__ = "Daniel Kühbacher"

import os

import pandas as pd
import numpy as np
import xlrd

from traffic_counts import TrafficCounts
import data_paths


class HbefaHotEmissions: 
    """Defines HBEFA parameters and classes, imports emission factors and 
    calculates hourly traffic emissions of different vehicle classes and components
    """
    
    vehicle_classes = ['PC', 'LCV', 'HGV', 'BUS', 'MOT']
    
    components = ['CO', 'NOx', 'PM', 'CO2(rep)', 'CO2(total)', 
                  'NO2', 'CH4', 'BC (exhaust)', 'CO2e']
    
    components = ['CO2(total)']
    
    # TODO Update threshols -> literature research/ use counting data
    service_thresholds = {'Motorway-Nat': [75, 80, 95, 100],
                          'Motorway-City': [75, 80, 95, 100],
                          'TrunkRoad/Primary-National': [50, 80, 90, 100],
                          'TrunkRoad/Primary-City': [75, 80, 95, 100],
                          'Distributor/Secondary': [50, 80, 90, 100],
                          'Local/Collector': [60, 80, 90, 100],
                          'Access-residential': [60, 80, 90, 100]}
    
    # level-of-service classes in HBEFA
    service_class = {0 : 'Freeflow',
                     1 : 'Heavy',
                     2 : 'Satur.',
                     3 : 'St+Go',
                     4 : 'St+Go2'}

    hbefa_road_abbreviations = {'Motorway-Nat': 'MW-Nat.',
                                'Motorway-City': 'MW-City',
                                'TrunkRoad/Primary-National': 'Trunk-Nat.', 
                                'TrunkRoad/Primary-City': 'Trunk-City',
                                'Distributor/Secondary': 'Distr.',
                                'Local/Collector': 'Local',
                                'Access-residential': 'Access'}
    
    praeamble = {'Urban': 'URB',
                 'Motorway': 'MW', 
                 'Rural': 'RUR'}
    
    # speed values available for different road categories in HBEFA
    hbefa_speed = {'Motorway-Nat': [80, 90, 100, 110, 120, 130],
                   'Motorway-City': [60, 70, 80, 90, 100, 110],
                   'TrunkRoad/Primary-National': [70, 80, 90, 100, 110, 120],
                   'TrunkRoad/Primary-City': [50, 60, 70, 80, 90],
                   'Distributor/Secondary': [30, 40, 50, 60, 70, 80],
                   'Local/Collector': [30, 40, 50, 60],
                   'Access-residential': [30, 40, 50]}
    
    # road gradients available in HBEFA
    hbefa_gradients = [-6, -4, -2, 0, 2, 4, 6]
    
    # multipliers to calculate the daily traffic volume as car units 
    # -> 1 Heavy truck equals to 3 car units
    #TODO Check HBS for exact values and cite them
    car_unit_factors = {'HGV': 3, 
                        'BUS': 3, 
                        'LCV':2, 
                        'PC':1, 
                        'MOT':1}


    def __init__(self):
        """Import emission factors and save as dict
        """
        self.ef_dict = {}
        for vehicle in HbefaHotEmissions.vehicle_classes:
             value = self._import_hbefa_ef(
                 eval(f'data_paths.EF_{vehicle}'))
             self.ef_dict.update({vehicle:value})


    def _import_hbefa_ef(self,
                         filepath:str) -> dict:
        """Import emission factors from HBEFA-exported *.XLS table
        
        Args:
            filepath (str): path to emission factor table
            
        Returns:
            dict: emission factors
        """
        try:
            workbook = xlrd.open_workbook(filepath, logfile=open(os.devnull, "w"))
            df = pd.read_excel(workbook) # read_excel accepts workbooks too
            columns_to_keep = ["Year", "Component", "TrafficSit",
                            "Gradient", "EFA_weighted"]
            df = df[columns_to_keep] # reduce to interesting columns
            df = df.set_index(['Year', 'TrafficSit', 'Gradient', 'Component'])
            df_dict = df.to_dict() # convert to dict for faster access
            print(f'Loaded emission factors from {filepath}')
            return df_dict
        
        except Exception as e: 
            print(f'Could not load table from {filepath}\n')
            print(e)
            return None
    
    
    def _convert_hbefa_speed(self,
                             road_type:str,
                             speed:int) -> int:
        """Converts speed value to closest speed value available in HEBFA

        Args:
            road_type (str): Road type 
            speed (int): Speed 

        Returns:
            int: HBEFA speed
        """
        hbefa_speed = min(HbefaHotEmissions.hbefa_speed[road_type],
                          key=lambda x: abs(x - speed))
        return hbefa_speed
    
    
    def _convert_hbefa_gradient(self,
                                road_gradient:float) -> str:
        """converts any road gradient to closest hbefa road gradient

        Args:
            road_gradient(float): Slope of the road

        Returns:
            str: road gradient string (e.g., '+6%')
        """
        hbefa_gradient = min(HbefaHotEmissions.hbefa_gradients,
                             key=lambda x: abs(x - road_gradient))
        hbefa_gradient_string = str(hbefa_gradient)+'%'
        return hbefa_gradient_string
    
    
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
        vc_ratio = (htv_car_unit / hour_capacity) * 100 #hourly volume capacity ratio [%]

        iterator = 0 # used to access the right service class
        # calculate category based on treshold provided in "service_thresholds"
        for tres in HbefaHotEmissions.service_thresholds[road_type]:
            if vc_ratio <= tres:
                break
            iterator += 1
        
        los = f'{praeamble}/{HbefaHotEmissions.hbefa_road_abbreviations[road_type]}/{str(hbefa_speed)}/{HbefaHotEmissions.service_class[iterator]}'
        return los
    
    
    def calculate_emissions_daily(self,
                                  dtv_vehicle:dict,
                                  diurnal_cycle_vehicle:pd.DataFrame,
                                  road_type:str,
                                  speed:int,
                                  slope:float,
                                  hour_capacity:int,
                                  year:int) -> dict:
        """Calculate emissions for a full day

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

        # convert input parameters to closest parameters available in HEBFA
        hbefa_gradient = self._convert_hbefa_gradient(slope)
        hbefa_speed = self._convert_hbefa_speed(road_type = road_type,
                                                speed = speed)
        
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
        
        vehicle_component_tuples = [(v,c) for v in HbefaHotEmissions.vehicle_classes
                                    for c in HbefaHotEmissions.components] 
        emissions_dict = {comb:0 for comb in vehicle_component_tuples}
        
        # calculate emissions for each hour of the day
        for i in range(0,24):
            # combine vehicle class and hourly traffic volume for each vehicle
            htv_hour = dict(zip(diurnal_cycle_vehicle.index, htv[i]))
            los_hour = los_class[i]
        
            # caclulate emissions for components and vehicle classes
            for v in HbefaHotEmissions.vehicle_classes:
                for c in HbefaHotEmissions.components:
                    try:
                        emissions_dict[(v,c)] += self.ef_dict[v]['EFA_weighted']\
                            [year, los_hour, hbefa_gradient, c] * htv_hour[v]
                    except: 
                        try:
                            # some gradient values are missing which could cause errors
                            emissions_dict[(v,c)] += self.ef_dict[v]['EFA_weighted']\
                                [year, los_hour, '0%', c] * htv_hour[v]
                        except Exception as e:
                            print('Exception ' + (str(e)))
                            print('Cannot calculate emissions.')
                            return 0
        return emissions_dict

# DEPRECATED
    def calculate_emissions_hourly(self,
                                  dtv_vehicle:dict,
                                  diurnal_cycle_vehicle:pd.DataFrame,
                                  road_type:str,
                                  speed:int,
                                  slope:float,
                                  hour_capacity:int,
                                  year:int) -> dict:
        """Calculate emissions for a full day

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

        # convert input parameters to closest parameters available in HEBFA
        hbefa_gradient = self._convert_hbefa_gradient(slope)
        hbefa_speed = self._convert_hbefa_speed(road_type = road_type,
                                                speed = speed)
        
        # caclulate hourly traffic count of each vehicle class
        dtv_array = np.array([dtv_vehicle[v] for v in diurnal_cycle_vehicle.index])
        htv = (np.transpose(diurnal_cycle_vehicle.to_numpy()) * dtv_array)

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
        
        # initialize dict for total emissions
        emission_day = dict()
        
        # calculate emissions for each hour of the day
        for i in range(0,24):
            # combine vehicle class and hourly traffic volume for each vehicle
            htv_hour = dict(zip(diurnal_cycle_vehicle.index, htv[i]))
            los_hour = los_class[i]
        
            # caclulate emissions for components and vehicle classes
            emission_hour = dict()
            for v in HbefaHotEmissions.vehicle_classes:
                #vehicle_emission_hour = dict()
                for c in HbefaHotEmissions.components:
                    try:
                        emission_hour.update({(v,c) : self.ef_dict[v]['EFA_weighted']\
                            [year,los_hour,hbefa_gradient,c] * htv_hour[v]})
                    except:
                        # some gradients are missing which could cause errors
                        emission_hour.update({(v,c) : self.ef_dict[v]['EFA_weighted']\
                            [year,los_hour,'0%',c] * htv_hour[v]})
                        
                        
                #emission_hour.update({v : vehicle_emission_hour})
                
            emission_day.update({i : emission_hour})
        return emission_day
        

if __name__ == '__main__':
    # test the function
    dtv_vehicle_test = {'PC':10000, 
                    'LCV': 1500, 
                    'HGV': 1000,
                    'MOT': 100, 
                    'BUS': 50}
    
    cycles = TrafficCounts()
    diurnal_cycles = cycles.get_hourly_scaling_factors(date='2019-01-02')
    
    t = HbefaHotEmissions()

    emissions = t.calculate_emissions_daily(dtv_vehicle = dtv_vehicle_test,
                    hour_capacity = 1000, 
                    diurnal_cycle_vehicle = diurnal_cycles,
                    road_type = 'Local/Collector', 
                    speed = 30, 
                    slope = 2,
                    year = 2019)
    
    print(emissions)
