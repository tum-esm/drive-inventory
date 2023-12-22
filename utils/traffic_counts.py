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
        self.vehicle_shares = self.fill_gaps(self.vehicle_shares, ['road_type', 'vehicle_class'], 0)
        
        # prepare annual cycles
        self.annual_cycles = _counting_df_norm[
            (_counting_df_norm['vehicle_class'] == 'SUM')]\
                .groupby(['road_type','date'])['daily_value'].median()
        self.annual_cycles = self.fill_gaps(self.annual_cycles, ['road_type'], 'daily_value')
        
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


    def fill_gaps(self, df, categories, value_column, arima_order=(12, 1, 1)): 
        """
        Takes a DataFrame, creates a complete date range for each category combination,
        merges with the original dataset, and fills missing values using ARIMA.

        :param df: The DataFrame to process.
        :param categories: List of column names to define unique category combinations.
        :param value_column: Name of the column containing the values for ARIMA.
        :param arima_order: Order of the ARIMA model.
        """
        df = df.reset_index()
        # Creating a date range from 2019-01-01 to 2022-12-31
        date_range = pd.date_range(start='2019-01-01', end='2022-12-31')

        # Create a template DataFrame with all combinations of categories and date
        unique_categories = [df[category].unique() for category in categories]
        all_combinations = product(*unique_categories, date_range)
        template_df = pd.DataFrame(all_combinations, columns=categories + ['date'])

        # Ensure 'date' column in df is in datetime format
        df['date'] = pd.to_datetime(df['date'])

        # Merge the template DataFrame with the original DataFrame
        merged_df = template_df.merge(df, on=categories + ['date'], how='left')

        # Fill missing values with ARIMA for each category combination
        for category_values in product(*unique_categories):
            filter_condition = np.logical_and.reduce([merged_df[cat] == val for cat, val in zip(categories, category_values)])
            train_set = merged_df.loc[filter_condition].copy()
            first_non_nan = train_set[value_column].first_valid_index()

            if first_non_nan is not None:
                train_set.loc[first_non_nan:, value_column].fillna(method='ffill', inplace=True)  # Forward fill
                train_set.set_index('date', inplace=True)
                train_set = train_set.asfreq(pd.infer_freq(train_set.index))

                arima = ARIMA(train_set[value_column], order=arima_order)
                predictions = arima.fit().predict()

                train_set[value_column].fillna(predictions, inplace=True)
                merged_df.loc[filter_condition, value_column] = train_set[value_column].values

        return merged_df




if __name__ == "__main__":
    count = TrafficCounts()
    print("Alpha: ", count.get_daily_scaling_factor(road_type ='Local/Collector', date = '2022-01-01'))
    print("Gamma: ", count.get_vehicle_share('Local/Collector','2022-01-01', 'HGV'))
    print("Beta: ", count.get_hourly_scaling_factors('2022-01-01', 'HGV'))
