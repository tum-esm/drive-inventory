"""Module to calculate cold start emissions based on HBEFA emission factors,
temperature and hourly activity profiles. 
"""
    
__version__ = 0.2
__author__ = "Daniel Kühbacher"

import pandas as pd
from typing import Literal

import data_paths

class HbefaColdEmissions: 
    """Class to calculate cold start emissions based on HBEFA emission factors.
    """
    
    _vehicle_classes = ['PC', 'LCV'] #no further classes available in HBEFA
    
    _all_components = ['NOx', 'FC', 'FC_MJ', 'PM', 'PN', 'CO2(rep)', 'CO2(total)',
                       'NO2', 'CH4', 'NMHC', 'Pb', 'SO2', 'Benzene', 'PM2.5',
                       'BC (exhaust)', 'HC', 'CO', 'CO2e']
    
    _temperature_range = [-10, -5, 0, 5, 10, 15, 20, 25]
    
    
    def __init__(self, 
                 components : list = ['CO2(rep)', 'NOx', 'CO']):
        """Load cold start emission factors from HBEFA excel file.
        Initilize for specific components.
        """
        assert all([c in HbefaColdEmissions._all_components for c in components])
        
        self.components = components
        
        # load emission factors from file
        self.emission_factors = self._import_hbefa_coldstart_ef(
            data_paths.EF_COLD)


    def _import_hbefa_coldstart_ef(self,
                                   filepath: str) -> dict:
        """Import cold start emission factors from HBEFA-exported *.XLS table
        
        Args:
            filepath (str): path to emission factor table
            
        Returns:
            dict: emission factors
        """
        try:
            
            ef = pd.read_csv(filepath, sep=';', encoding='latin_1',
                on_bad_lines= 'skip', decimal=',')

            columns_to_keep = ['VehCat', 'Year', 'Component',
                                'AmbientCondPattern', 'EFA_weighted']

            # convert Vehicle Categorie to common acronym
            ef.loc[ef['VehCat']=='pass. car', 'VehCat'] = 'PC'
            ef = ef[columns_to_keep] # reduce to interesting columns
            ef = ef.set_index(['VehCat', 'Year','Component', 'AmbientCondPattern'])
            print(f'Loaded emission factors from {filepath}')
            return ef
    
        except Exception as e:
            print(e)
            print(f'Could not load table from {filepath}\n')
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
        hbefa_temperature = min(HbefaColdEmissions._temperature_range,
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
                                  vehicle_starts : int,
                                  hourly_temperature: float,
                                  vehicle_class: Literal['PC', 'LCV'],
                                  year: int) -> float:
        """Calculates the daily cold start emission based on ambient condition pattern

        Args:
            hourly_temperature (float): _description_
            hourly_starts (float): _description_
            vehicle_class (str): _description_
            year (int): _description_

        Returns:
            float: emissions
        """
        
        amb = self._calc_ambient_condition_pattern(hourly_temperature)
        em = self.emission_factors.loc[vehicle_class, year, self.components, amb]['EFA_weighted']
        e = em.droplevel(['VehCat', 'Year', 'AmbientCondPattern'])
        
        return e * vehicle_starts


if __name__ == '__main__':
    """Example usage and test of the HBEFA cold start emissions class.
    """
    c = HbefaColdEmissions()
    
    temperature = 16.01
    
    k = c.calculate_emission_hourly(vehicle_starts = 10,
                                    hourly_temperature = temperature,
                                    vehicle_class = 'PC',
                                    year = 2019)
    
    print(k)