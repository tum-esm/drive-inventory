"""_summary_
"""
    
__version__ = 0.1
__author__ = "Daniel Kühbacher"

import os

import pandas as pd
import xlrd

import data_paths

class HbefaColdEmissions: 
    """_summary_
    """
    
    vehicle_classes = ['pass. car', 'LCV']
    
    components = ['CO', 'NOx', 'PM', 'CO2(rep)', 'CO2(total)', 
                  'NO2', 'CH4', 'BC (exhaust)', 'CO2e']
    
    temperature_range = [-10, -5, 0, 5, 10, 15, 20, 25]
    
    
    def __init__(self): 
        self.emission_factors = self._import_hbefa_coldstart_ef(
            data_paths.EF_ColdStart)
                
    
    def _import_hbefa_coldstart_ef(self,
                                  filepath:str) -> dict:
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
            df = df[columns_to_keep] # reduce to interesting columns
            df = df.set_index(['VehCat', 'Year','Component', 'AmbientCondPattern'])
            #df_dict = df.to_dict() # convert to dict for faster access
            print(f'Loaded emission factors from {filepath}')
            return df
    
        except Exception as e: 
            print(f'Could not load table from {filepath}\n')
            print(e)
            return None
    
    
    def _calc_ambient_condition_patter(self,
                                       temperature: float) -> str: 
        
        hbefa_temperature = min(HbefaColdEmissions.temperature_range,
                                key=lambda x: abs(x - temperature))
        
        # no further information for trip duration and length is available
        trip_length = 'dØ'
        trip_duration = 'tØ'
        
        if hbefa_temperature < 0: 
            temp_string = f'T-{abs(hbefa_temperature)}°C'
        else: 
            temp_string = f'T+{abs(hbefa_temperature)}°C'
        
        return temp_string + ',' + trip_duration + ',' + trip_length
        
    
    def calculate_emission_daily(self,
                                 hourly_temperature: list[24],
                                 hourly_starts: list[24],
                                 vehicle_class:str,
                                 year: int) -> float: 
        
        ambient_conditions = [self._calc_ambient_condition_patter(
            temperature=x) for x in hourly_temperature]
        
        emissions_list = list()
        
        for i in range(0,24): 
            amb = ambient_conditions[i]
            n_starts = hourly_starts[i]
            em = self.emission_factors.loc[vehicle_class, year,:, amb]['EFA_weighted'] * n_starts
            
            emissions_list.append(em)
            
        pd.concat(emissions_list, axis =0)
        return pd.concat(emissions_list, axis=1).sum(axis =1)
    
    
if __name__ == '__main__': 
    c = HbefaColdEmissions()
    
    temperature = list(range(0,24))
    starts = [100]*24
    
    k = c.calculate_emission_daily(hourly_temperature = temperature, 
                                 hourly_starts = starts, 
                                 vehicle_class = 'pass. car',
                                 year=2019)
    
    print(k)