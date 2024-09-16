"""Module to calculate cold start emissions based on HBEFA emission factors,
temperature and hourly activity profiles. 
"""
    
__version__ = 0.2
__author__ = "Daniel Kühbacher"

import os

import pandas as pd
import xlrd

from typing import Literal

import data_paths

class HbefaColdEmissions: 
    """Class to calculate cold start emissions based on HBEFA emission factors.
    """
    
    vehicle_classes = ['PC', 'LCV'] #no further classes available in HBEFA
    
    components = ['CO', 'NOx', 'PM', 'CO2(rep)', 'CO2(total)', 
                  'NO2', 'CH4', 'BC (exhaust)', 'CO2e']
    
    temperature_range = [-10, -5, 0, 5, 10, 15, 20, 25]
    
    
    def __init__(self):
        """Load cold start emission factors from HBEFA excel file.
        """
        self.emission_factors = self._import_hbefa_coldstart_ef(
            data_paths.EF_ColdStart)


    def _import_hbefa_coldstart_ef(self,
                                   filepath: str) -> dict:
        """Import cold start emission factors from HBEFA-exported *.XLS table
        
        Args:
            filepath (str): path to emission factor table
            
        Returns:
            dict: emission factors
        """
        try:
            workbook = xlrd.open_workbook(filepath, logfile=open(os.devnull, "w"))
            df = pd.read_excel(workbook) # read_excel accepts workbooks too
            columns_to_keep = ['VehCat', 'Year', 'Component',
                               'AmbientCondPattern', 'EFA_weighted']

            # convert Vehicle Categorie to common acronym
            df.loc[df['VehCat']=='pass. car', 'VehCat'] = 'PC'
            
            df = df[columns_to_keep] # reduce to interesting columns
            df = df.set_index(['VehCat', 'Year','Component', 'AmbientCondPattern'])
            print(f'Loaded emission factors from {filepath}')
            return df
    
        except Exception as e: 
            print(f'Could not load table from {filepath}\n')
            print(e)
            return None


    def _calc_ambient_condition_pattern(self,
                                       temperature: float) -> str:
        """Calculates ambient conditino pattern to select the right emission factor.

        Args:
            temperature (float): actual ambient temperature

        Returns:
            str: Strint representing the ambient condition pattern
        """
        # calculate closest temperature in HBEFA range
        hbefa_temperature = min(HbefaColdEmissions.temperature_range,
                                key=lambda x: abs(x - temperature))
        
        # no further information for trip duration and length is available
        trip_length = 'dØ'
        trip_duration = 'tØ'
        
        if hbefa_temperature < 0: 
            temp_string = f'T-{abs(hbefa_temperature)}°C'
        else: 
            temp_string = f'T+{abs(hbefa_temperature)}°C'
        # the return string can be used to access the right emission factor in HBEFA
        return temp_string + ',' + trip_duration + ',' + trip_length


    def calculate_emission_hourly(self,
                                 hourly_temperature: float,
                                 vehicle_class: Literal['PC', 'LCV'],
                                 year: int) -> float:
        """calculates the daily cold start emission based on ambient condition pattern

        Args:
            hourly_temperature (float): _description_
            hourly_starts (float): _description_
            vehicle_class (str): _description_
            year (int): _description_

        Returns:
            float: emissions
        """
        
        amb = self._calc_ambient_condition_pattern(hourly_temperature)
        em = self.emission_factors.loc[vehicle_class, year, :, amb]['EFA_weighted']
            
        return em


if __name__ == '__main__':
    """Example usage and test of the HBEFA cold start emissions class.
    """
    c = HbefaColdEmissions()
    
    temperature = 23.01
    
    k = c.calculate_emission_hourly(hourly_temperature = temperature,
                                 vehicle_class = 'PC',
                                 year=2019)
    
    print(k)