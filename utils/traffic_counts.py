"""tbd
"""
__version__ = 2.0
__author__ = 'Ali Ahmad Khan'

import data_paths
import pandas as pd
from datetime import datetime
import excel_calendar

class TrafficCounts:
    """ Reads combined counting data calculates and provides an interface to the traffic cycles.
    """ 
    
    def __init__(self):
        """__summary__
        """
        file_path = data_paths.COUNTING_PATH + 'counting_data_combined.parquet'
        _counting_df = pd.read_parquet(file_path)
        self.counting_df = self._normalize_count(_counting_df)

        # prepare datframe for dtv
        self.road_type_dtv = _counting_df[(_counting_df['date'].between('2019-01-01','2019-12-31')) &
                                     (_counting_df['day_type']==0) & 
                                     (_counting_df['vehicle_class']=='SUM') &
                                     (_counting_df['complete'])] \
                        .groupby(['road_type'])['daily_value'].median().reset_index()
        
        # prepare dataframes for vehicle share calculation
        self._daily_median = _counting_df[_counting_df['complete']]\
            .groupby(['vehicle_class', 'road_type','date'])['daily_value'].median()

        self._sum_cnt = pd.concat([self._daily_median['BUS'],
                                   self._daily_median['LCV'],
                                   self._daily_median['MOT'],
                                   self._daily_median['PC'], 
                                   self._daily_median['HGV']], 
                                   axis=1).fillna(0).sum(axis=1)
            
    
    def _normalize_count(self, df:pd.DataFrame) -> pd.DataFrame:
        """Normalizes all complete counting time series to their 2019 weekday reference.
        
        Args:
            df (pd.DataFrame): _description_
        Returns:
            pd.DataFrame:
        """
        mean_counts = df[(df['date'].between('2019-01-01','2019-12-31')) &
                        (df['day_type']==0) & 
                        (df['complete'])] \
        .groupby(['road_link_id','vehicle_class'])['daily_value'].mean().reset_index()
        
        counts_norm = pd.merge(df, mean_counts, on=['road_link_id','vehicle_class'], suffixes=('','_mean'))
        counts_norm['daily_value'] = counts_norm['daily_value'] / counts_norm['daily_value_mean']
        counts_norm = counts_norm.drop('daily_value_mean', axis = 1)
        
        # normalize daily cycles
        counts_norm.iloc[:,-25:] = counts_norm.iloc[:,-25:].div(counts_norm.iloc[:,-25:].sum(axis =1), axis = 0)
        return counts_norm
    

    def get_dtv(self) -> float:

        # Calculates a constant for the traffic through out the year of 2019
        dtv = self.road_type_dtv['daily_value'].median()
        
        return round(dtv, 2) 
    
    def get_daily_scaling_factor(self, date: str) -> float:
        
        # Calculates the factor of vehicles on a given date compared to vehicle counts in 2019
        daily_scaling_factor = self.counting_df[(self.counting_df['date'] == date) &
                    (self.counting_df['vehicle_class'] == 'SUM') &
                    (self.counting_df['complete'])]['daily_value'].median()

        return round(daily_scaling_factor, 2)

    def get_vehicle_shares(self, road_type: str, date: str, vehicle_class: str) -> float:

        # Calculates Vehicles Sharefor all dates 
        shares = self._daily_median[vehicle_class]/self._sum_cnt

        # returns vehicle share for a specific vehicle class on a specific date
        return round(shares.loc[road_type,date],2)

    def get_hourly_scaling_factor(self, datestring: str, hour: int, vehicle_class: str):

        # since the diurnal cycles are not significantly different between differnt road types, they were aggregated to one single road type and month
        irrelevant_rows = ['road_type','road_link_id','daily_value', 'complete']
        d_cycles = self.counting_df.drop(irrelevant_rows, axis=1).set_index('date').groupby(['day_type', 'vehicle_class']).resample('1m').mean()
        d_cycles = d_cycles.reset_index()
        d_cycles.insert(2, 'month', d_cycles['date'].dt.month)
        d_cycles.insert(2, 'year', d_cycles['date'].dt.year)
        d_cycles = d_cycles.drop('date', axis = 1)
        d_cycles = d_cycles.set_index(['year','month', 'day_type'])
        
        # Get daytype, year and month from our datestring
        cal = excel_calendar.Calendar()
        dt = cal.get_day_type_combined(datestring)
        year = datetime.strptime(datestring, '%Y-%m-%d').year
        month = datetime.strptime(datestring, '%Y-%m-%d').month

        # Receive the vehicles shares for the given year, month and daytype
        d_cycles = d_cycles.sort_index()
        cycle = d_cycles.loc[year, month, dt].set_index('vehicle_class')

        # Get the hourly scaling factor for a specific vehicle class for a specific hour
        return round(cycle.loc[vehicle_class].iloc[hour],2)

        
if __name__ == "__main__":
    count = TrafficCounts()
    total = 0
    print("DTV: ", count.get_dtv())
    print("Alpha: ", count.get_daily_scaling_factor('2022-01-01'))
    print("Gamma: ", count.get_vehicle_shares('Local/Collector','2022-01-01', 'HGV'))
    print("Beta: ", count.get_hourly_scaling_factor('2022-01-01', 12, 'HGV'))


    