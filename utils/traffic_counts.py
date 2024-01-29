"""tbd
"""
__version__ = 0.3
__author__ = ['Ali Ahmad Khan', 'Daniel Kühbacher']

import pandas as pd
import numpy as np
from itertools import product
from statsmodels.tsa.arima.model import ARIMA

from datetime import datetime

import data_paths
import excel_calendar

class TrafficCounts:
    """ Reads combined counting data calculates and provides an interface to the traffic cycles.
    """

    def __init__(self):
        """__summary__
        """
        # initialize calendar
        self.cal = excel_calendar.Calendar()
        
        # read and import counting data
        _file_path = data_paths.COUNTING_PATH + 'counting_data_combined.parquet'
        _counting_df = pd.read_parquet(_file_path)
        
        # get information from the counting data
        self.date_start = _counting_df['date'].min()
        self.date_end = _counting_df['date'].max()
        self.road_types = list(_counting_df['road_type'].unique())
        self.vehicle_types = list(_counting_df['vehicle_class'].unique())
        self.vehicle_types.remove('SUM')
        
        # normalice counting dataframe
        _counting_df_norm = self._normalize_count(_counting_df)
        
        # prepare dataframes for vehicle share calculation
        _daily_median = _counting_df[
            (_counting_df['complete']) &
            (_counting_df['vehicle_class'].isin(['HGV', 'LCV', 'PC', 'MOT', 'BUS']))]\
                .groupby(['vehicle_class', 'road_type','date'])['daily_value'].median()
        # TODO -> gapfill daily median dataframe
        print(_daily_median)
        _daily_median = self.fill_gaps(df = _daily_median,categories = ['vehicle_class','road_type'], value_column = 'daily_value')
        _daily_median = _daily_median.groupby(['vehicle_class', 'road_type','date'])['daily_value'].median()
        print(_daily_median)
        _sum_cnt = pd.concat([_daily_median['BUS'],
                              _daily_median['LCV'],
                              _daily_median['MOT'],
                              _daily_median['PC'],
                              _daily_median['HGV']], axis=1).fillna(0).sum(axis=1)
        
        self.vehicle_shares = _daily_median/_sum_cnt
        
        # prepare annual cycles
        self.annual_cycles = _counting_df_norm[
            (_counting_df_norm['vehicle_class'] == 'SUM')]\
                .groupby(['road_type','date'])['daily_value'].median()
        # TODO -> gapfill annual cycles
        self.annual_cycles = self.fill_gaps(df = self.annual_cycles,categories = ['road_type'], value_column = 'daily_value')
        self.annual_cycles = self.annual_cycles.set_index(['road_type','date'])
        # prepare daily cycles
        _irrelevant_rows = ['road_type', 'road_link_id', 'daily_value', 'complete', 'valid']
        _d_cycles = _counting_df.drop(_irrelevant_rows, axis=1).set_index('date')\
            .groupby(['day_type', 'vehicle_class']).resample('1m').median()
            
        # normalize daily cycles
        _d_cycles.iloc[:,-24:] = _d_cycles.iloc[:,-24:].div(_d_cycles.iloc[:,-24:].sum(axis =1), axis = 0)
        _d_cycles = _d_cycles.reset_index()
        _d_cycles.insert(2, 'month', _d_cycles['date'].dt.month)
        _d_cycles.insert(2, 'year', _d_cycles['date'].dt.year)
        _d_cycles = _d_cycles.drop('date', axis = 1)
        
        self.daily_cycles = _d_cycles.set_index(
            ['year', 'month', 'day_type', 'vehicle_class'])
                
        # prepare combined timeprofiles
        self.timeprofile = dict()
        for road_type in self.road_types:
            self.timeprofile.update({road_type:self._combine_time_profile(road_type)})
            
    
    def _combine_time_profile(self, road_type:str) -> pd.DataFrame:
        """Combines annual activity,vehicle share and daily cycles to a hourly profile

        Args:
            road_type (str): Type of the road

        Returns:
            pd.DataFrame: time profile of specific road type
        """

        time_profile = pd.DataFrame()
        # make datetime index
        index = pd.date_range(start = self.date_start,
                              end = self.date_end,
                              freq = '1d')
        
        for idx in index:
            datestring = idx.strftime('%Y-%m-%d')
            df = pd.DataFrame(index =pd.date_range(start=idx, periods = 24, freq='1h'))

            try: 
                activity = self.get_daily_scaling_factors(datestring).loc[road_type]
                for vc in self.vehicle_types:
                    share = self.get_vehicle_share(datestring).loc[road_type, vc]
                    diurnal_cycle = self.get_hourly_scaling_factors(datestring).loc[vc]
                    diurnal_cycle = diurnal_cycle * activity * share
                    df[vc] = np.array(diurnal_cycle)
            except:
                for vc in self.vehicle_types:
                    # if no valid data is available
                    df[vc] = np.array([0]*24)
            time_profile = pd.concat([time_profile, df]) # append time profile 
        
        return time_profile
            
            
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
        # mean normweekday count (day_type =0) of complete counting timeseries (complete = True)
        # inter-quantile-range mean to reduce outlier influence
        df_mean = df[(df['date'].between('2019-01-01','2019-12-31')) &
                        (df['day_type']==0) & 
                        (df['complete'])] \
        .groupby(['road_link_id','vehicle_class'])['daily_value'].apply(self._iqr_mean).reset_index()
        
        df_norm = pd.merge(df, df_mean, on=['road_link_id','vehicle_class'], suffixes=('','_mean'))
        df_norm['daily_value'] = df_norm['daily_value'] / df_norm['daily_value_mean']
        df_norm = df_norm.drop('daily_value_mean', axis = 1)

        return df_norm


    def get_daily_scaling_factors(self,
                                 date: str) -> pd.Series:
        """returns daily scaling factor of all road types as pd.Series
        Args:
            date (str): date string

        Returns:
            pd.Series: daily scaling factors for each road type
        """
        day_factors = self.annual_cycles.loc[:, date]
        return day_factors


    def get_vehicle_share(self,
                           date:str) -> pd.DataFrame:
        """returns dataframe with vehicle shares of different vehicle types and road types s

        Args:
            date (str): _description_

        Returns:
            float: _description_
        """
        # Calculates Vehicles Sharefor all dates 
        shares = self.vehicle_shares[:,date,:].reset_index()
        shares = shares.pivot(columns='vehicle_class', index ='road_type', values = 0)
        return shares


    def get_hourly_scaling_factors(self, 
                                  date:str):
        """_summary_
        Args:
            date (str): _description_
        Returns:
            _type_: _description_
        """
        dt = self.cal.get_day_type_combined(date)
        year = datetime.strptime(date, '%Y-%m-%d').year
        month = datetime.strptime(date, '%Y-%m-%d').month

        cycle = self.daily_cycles.loc[year, month, dt, :]
        cycle = cycle.drop(['SUM'])
        return cycle


    def fill_gaps(self, df, categories, value_column): 
        """
        Takes a DataFrame, creates a complete date range for each category combination,
        merges with the original dataset, and fills missing values using day type averaging

        :param df: The DataFrame to process.
        :param categories: List of column names to define unique category combinations.
        :param value_column: Name of the column containing the values
        """
        df = df.reset_index()
  
        filled_df = pd.DataFrame()
        # Creating a date range from 2019-01-01 to 2022-12-31
        date_range = pd.date_range(start=df['date'].min(), end='2022-12-31')

        # Create a template DataFrame with all combinations of categories and date
        unique_categories = [df[category].unique() for category in categories]
        all_combinations = product(*unique_categories, date_range)
        template_df = pd.DataFrame(all_combinations, columns=categories + ['date'])

        # Ensure 'date' column in df is in datetime format
        df['date'] = pd.to_datetime(df['date'])

        # Merge the template DataFrame with the original DataFrame
        merged_df = template_df.merge(df, on=categories + ['date'], how='left')
        for category_values in product(*unique_categories):
                filter_condition = np.logical_and.reduce([merged_df[cat] == val for cat, val in zip(categories, category_values)])
                train_set = merged_df.loc[filter_condition].copy()
                unchanged_set = merged_df.loc[filter_condition].copy()
                first_non_nan = train_set[value_column].first_valid_index()
                day_types = {date:self.cal.get_day_type_combined(date) for date in train_set['date']}
                train_set.insert(3, 'day_type',train_set['date'].map(day_types))
                if first_non_nan is not None:
                    # Extract year and month from the date column
                    train_set['year'] = train_set['date'].dt.year
                    train_set['month'] = train_set['date'].dt.month

                    # Group by year, month, and day_type, then calculate the mean
                    mean_cycle_values = train_set.groupby(['year', 'month', 'day_type'])[value_column].mean()
                    # Flatten the multi-index DataFrame
                    mean_cycle_values = mean_cycle_values.reset_index()

                    # Ensure that the DataFrame is sorted
                    mean_cycle_values.sort_values(by=['year', 'day_type', 'month'], inplace=True)
                    mean_cycle_values.set_index(['year', 'day_type', 'month'], inplace=True)

                    # Calculate the rolling mean including one month before and after
                    mean_cycle_values = mean_cycle_values[value_column].shift(1).rolling(window=3, min_periods=1).mean().shift(-2)
                    mean_cycle_values.bfill(inplace=True)

                    # Reset the index of mean_cycle_values
                    mean_cycle_values = mean_cycle_values.reset_index()

                    # Merge mean_cycle_values with avg_method
                    train_set = pd.merge(train_set, mean_cycle_values, on=['year', 'day_type', 'month'], how='left', suffixes=('', '_mean'))

                    # Fill NaN values in avg_method's daily_value with the mean values
                    train_set['daily_value'].fillna(train_set[value_column+'_mean'], inplace=True)

                    # Optionally, if you don't want to keep the extra column:
                    train_set=train_set.reset_index()
                    train_set.drop(columns=[value_column+'_mean','year','month','day_type','index'], inplace=True)
        

                    filled_df = pd.concat([filled_df, train_set])

                    train_set.set_index('date', inplace=True)

        filled_df.reset_index(inplace=True)
        filled_df.drop(columns=['index'], inplace=True)

        return filled_df


if __name__ == "__main__":
    count = TrafficCounts()
    print("Alpha: \n", count.get_daily_scaling_factors(date = '2022-01-01'))
    print("Gamma: \n", count.get_vehicle_share(date = '2022-01-01'))
    print("Beta: \n", count.get_hourly_scaling_factors('2022-01-01'))
