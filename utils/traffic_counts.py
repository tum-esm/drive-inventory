"""tbd
"""
__version__ = 0.3
__author__ = ['Ali Ahmad Khan', 'Daniel Kühbacher']

import data_paths
import pandas as pd
import numpy as np
from datetime import datetime
import excel_calendar

class TrafficCounts:
    """ Reads combined counting data calculates and provides an interface to the traffic cycles.
    """ 

    def __init__(self):
        """__summary__
        """
        # read and import counting data
        _file_path = data_paths.COUNTING_PATH + 'counting_data_combined.parquet'
        _counting_df = pd.read_parquet(_file_path)
        
        # normalice counting dataframe
        _counting_df_norm = self._normalize_count(_counting_df)
        
        # prepare dataframes for vehicle share calculation
        _daily_median = _counting_df[
            (_counting_df['complete']) &
            (_counting_df['vehicle_class'].isin(['HGV', 'LCV', 'PC', 'MOT', 'BUS']))]\
                .groupby(['vehicle_class', 'road_type','date'])['daily_value'].median()

        _sum_cnt = pd.concat([_daily_median['BUS'],
                              _daily_median['LCV'],
                              _daily_median['MOT'],
                              _daily_median['PC'],
                              _daily_median['HGV']],axis=1).fillna(0).sum(axis=1)
        
        self.vehicle_shares = _daily_median/_sum_cnt
        
        # prepare annual cycles
        self.annual_cycles = _counting_df_norm[
            (_counting_df_norm['vehicle_class'] == 'SUM')]\
                .groupby(['road_type','date'])['daily_value'].median()
                
        # prepare daily cycles
        _irrelevant_rows = ['road_type', 'road_link_id', 'daily_value', 'complete', 'valid']
        _d_cycles = _counting_df_norm.drop(_irrelevant_rows, axis=1).set_index('date')\
            .groupby(['day_type', 'vehicle_class']).resample('1m').mean()
        _d_cycles = _d_cycles.reset_index()
        _d_cycles.insert(2, 'month', _d_cycles['date'].dt.month)
        _d_cycles.insert(2, 'year', _d_cycles['date'].dt.year)
        _d_cycles = _d_cycles.drop('date', axis = 1)
        
        self.daily_cycles = _d_cycles.set_index(
            ['year', 'month', 'day_type', 'vehicle_class'])
        
        # initialize calendar
        self.cal = excel_calendar.Calendar()

    def _iqr_mean(self, 
                  input:pd.DataFrame, 
                  iqr_range:tuple = (5,95)) -> float: 
        """Calculates inter quantile range mean. 5 - 95% range is predefined

        Args:
            input (pd.Dataframe): dataframe to calculate the mean from.
            iqr_range (tuple, optional): _description_. Defaults to (5,95).

        Returns:
            float: iqr-mean of the input dataframe
        """
        lower_bound = np.percentile(input, iqr_range[0])
        upper_bound = np.percentile(input, iqr_range[1])
        iqr_mean = np.mean(input[(input >= lower_bound) & (input <= upper_bound)])
        return iqr_mean

    def _normalize_count(self,
                         df:pd.DataFrame) -> pd.DataFrame:
        """Normalizes all complete counting time series to their 2019 weekday reference.
        
        Args:
            df (pd.DataFrame): traffic counting data
        Returns:
            pd.DataFrame: normalized conting data
        """
        df_mean = df[(df['date'].between('2019-01-01','2019-12-31')) &
                        (df['day_type']==0) & 
                        (df['complete'])] \
        .groupby(['road_link_id','vehicle_class'])['daily_value'].apply(self._iqr_mean).reset_index()
        
        df_norm = pd.merge(df, df_mean, on=['road_link_id','vehicle_class'], suffixes=('','_mean'))
        df_norm['daily_value'] = df_norm['daily_value'] / df_norm['daily_value_mean']
        df_norm = df_norm.drop('daily_value_mean', axis = 1)
        
        # normalize daily cycles
        df_norm.iloc[:,-24:] = df_norm.iloc[:,-24:].div(df_norm.iloc[:,-24:].sum(axis =1), axis = 0)
        return df_norm

    def get_daily_scaling_factor(self, 
                                 road_type: str, 
                                 date: str) -> float:
        """_summary_

        Args:
            date (str): _description_

        Returns:
            float: _description_
        """
        
        day_factor = self.annual_cycles.loc[road_type, date]
        return day_factor

    def get_vehicle_share(self, 
                           road_type:str, 
                           date:str, 
                           vehicle_class:str) -> float:
        """_summary_

        Args:
            road_type (str): _description_
            date (str): _description_
            vehicle_class (str): _description_

        Returns:
            float: _description_
        """
        # Calculates Vehicles Sharefor all dates 
        
        share = self.vehicle_shares.loc[road_type, date, vehicle_class]
        return share

    def get_hourly_scaling_factors(self, 
                                  datestring:str,
                                  vehicle_class:str):
        """_summary_

        Args:
            datestring (str): _description_
            hour (int): _description_
            vehicle_class (str): _description_

        Returns:
            _type_: _description_
        """
        
        dt = self.cal.get_day_type_combined(datestring)
        year = datetime.strptime(datestring, '%Y-%m-%d').year
        month = datetime.strptime(datestring, '%Y-%m-%d').month

        cycle = self.daily_cycles.loc[year, month, dt, vehicle_class]
        return cycle


if __name__ == "__main__":
    count = TrafficCounts()
    print("Alpha: ", count.get_daily_scaling_factor(road_type ='Local/Collector', date = '2022-01-01'))
    print("Gamma: ", count.get_vehicle_share('Local/Collector','2022-01-01', 'HGV'))
    print("Beta: ", count.get_hourly_scaling_factors('2022-01-01', 'HGV'))
