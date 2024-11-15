"""Loads and processes preprocessed traffic counting data and provides an interface 
to the traffic cycles. 
Calculates daily, annual and hourly cycles for traffic counting data.
"""
__version__ = 0.3
__author__ = ['Ali Ahmad Khan', 'Daniel Kühbacher']

import pandas as pd
import numpy as np

from itertools import product
from datetime import datetime

import data_paths
import excel_calendar


class TrafficCounts:
    """ Reads combined counting data calculates, and provides an interface 
    to the traffic cycles.
    """
    
    ref_year = '2019' # reference year for normalization
    ref_day_type = 0 # normal weekday (see definition in excel calendar

    def __init__(self, init_timeprofile = True):
        """Loads traffic couning data and preprocesses daily, annual and hourly cycles.
        """
        # initialize calendar object
        self.cal = excel_calendar.Calendar()
        
        # read and import traffic counting data
        _file_path = data_paths.COUNTING_PATH + 'counting_data_combined_until2023.parquet'
        _counting_df = pd.read_parquet(_file_path)
        
        # get information from the counting data
        self.date_start = _counting_df['date'].min()
        self.date_end = _counting_df['date'].max()
        self.road_types = list(_counting_df['scaling_road_type'].unique())
        self.vehicle_classes = list(_counting_df['vehicle_class'].unique())
        self.vehicle_classes.remove('SUM') # SUM type is not an idividual vehicle type
        
        # prepare dataframes for vehicle share calculation
        # daily median count for each vehicle class and scaling road type; 
        # only complete and valid data is considered
        _daily_median = _counting_df[(_counting_df['complete']) &
                                    (_counting_df['valid']) &
                                    (_counting_df['vehicle_class'].isin(self.vehicle_classes))]\
                                        .groupby(['vehicle_class',
                                                  'scaling_road_type',
                                                  'date'])['daily_value'].median()
        _daily_median = self.fill_gaps(df = _daily_median,
                                    categories = ['vehicle_class', 'scaling_road_type'],
                                    value_column = 'daily_value')
        _daily_median = _daily_median.groupby(['vehicle_class', 
                                               'scaling_road_type',
                                               'date'])['daily_value'].median()
        _sum_cnt = pd.concat([_daily_median['BUS'],
                              _daily_median['LCV'],
                              _daily_median['MOT'],
                              _daily_median['PC'],
                              _daily_median['HGV']],axis=1).fillna(0).sum(axis=1)
        self.vehicle_shares = _daily_median/_sum_cnt
    
        # prepare annual cycles
        # normalize counting dataframe
        _counting_df_norm = self._normalize_count(_counting_df)
        self.annual_cycles = _counting_df_norm[
            (_counting_df_norm['vehicle_class'] == 'SUM')]\
                .groupby(['scaling_road_type', 'date'])['daily_value'].median()
        self.annual_cycles = self.fill_gaps(df = self.annual_cycles,
                                            categories = ['scaling_road_type'],
                                            value_column = 'daily_value')
        self.annual_cycles = self.annual_cycles.groupby(['scaling_road_type',
                                                         'date'])['daily_value'].median()
        
        # prepare daily cycles
        _irrelevant_rows = ['scaling_road_type', 'road_type', 'road_link_id',
                            'daily_value', 'complete', 'valid']
        hour_column_names = [str(i) for i in range(0,24)]
        _d_cycles = _counting_df.drop(_irrelevant_rows, axis=1).set_index('date')\
            .groupby(['day_type', 'vehicle_class'])[hour_column_names]\
                .resample('1m').median()
            
        # normalize daily cycles
        _d_cycles[hour_column_names] = _d_cycles[hour_column_names]\
            .div(_d_cycles[hour_column_names].sum(axis= 1), axis = 0)
        _d_cycles = _d_cycles.reset_index()
        _d_cycles.insert(2, 'month', _d_cycles['date'].dt.month)
        _d_cycles.insert(2, 'year', _d_cycles['date'].dt.year)
        _d_cycles = _d_cycles.drop('date', axis = 1)
        self.daily_cycles = _d_cycles.set_index(
            ['year', 'month', 'day_type', 'vehicle_class'])
                
        # prepare combined timeprofiles
        if init_timeprofile:
            self.timeprofile = dict()
            for rt in self.road_types:
                self.timeprofile.update({rt:self._combine_time_profile(rt)})
           
    
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
                for vc in self.vehicle_classes:
                    share = self.get_vehicle_share(datestring).loc[road_type, vc]
                    diurnal_cycle = self.get_hourly_scaling_factors(datestring).loc[vc]
                    diurnal_cycle = diurnal_cycle * activity * share
                    df[vc] = np.array(diurnal_cycle)
            except Exception:
                for vc in self.vehicle_classes:
                    # if no valid data is available
                    df[vc] = np.array([0]*24)
            time_profile = pd.concat([time_profile, df]) # append time profile 
        
        return time_profile
            
            
    def _iqr_mean(self, 
                  input:pd.DataFrame, 
                  iqr_range:tuple = (2.5, 97.5)) -> float: 
        """Calculates inter quantile range mean. 5 - 95% range is predefined

        Args:
            input (pd.Dataframe): dataframe to calculate the mean from.
            iqr_range (tuple, optional): _description_. Defaults to (5,95).
        Returns:
            float: iqr-mean of the input dataframe
        """
        iqr_mean = np.mean(input[
            (input >= np.percentile(input, iqr_range[0])) &\
            (input <= np.percentile(input, iqr_range[1]))])
        return iqr_mean


    def _normalize_count(self,
                         df:pd.DataFrame) -> pd.DataFrame:
        """Normalizes all complete counting time series to their 2019 weekday reference.
        Args:
            df (pd.DataFrame): traffic counting data
        Returns:
            pd.DataFrame: normalized conting data
        """
        # mean normweekday count (day_type =0) of complete counting timeseries
        # inter-quantile-range mean to reduce outlier influence
        df_mean = df[(df['date'].between(f'{TrafficCounts.ref_year}-01-01',
                                         f'{TrafficCounts.ref_year}-12-31')) &
                        (df['day_type']== TrafficCounts.ref_day_type) & 
                        (df['complete'])] \
                            .groupby(['road_link_id', 'vehicle_class'])['daily_value']\
                                .apply(self._iqr_mean).reset_index()
        
        df_norm = pd.merge(df, df_mean, 
                           on=['road_link_id','vehicle_class'], suffixes=('', '_mean'))
        df_norm['daily_value'] = df_norm['daily_value'] / df_norm['daily_value_mean']
        df_norm = df_norm.drop('daily_value_mean', axis = 1)

        return df_norm


    def get_daily_scaling_factors(self,
                                 date: datetime) -> pd.Series:
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
        """returns dataframe with vehicle shares of different vehicle and road types

        Args:
            date (str): _description_
        Returns:
            float: _description_
        """
        # Calculates Vehicles Sharefor all dates 
        shares = self.vehicle_shares[:,date,:].reset_index()
        shares = shares.pivot(columns='vehicle_class', index ='scaling_road_type', values = 0)
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
        
        # Creating a date range from minimum to the maximum date of the dataframe
        date_range = pd.date_range(start=df['date'].min(), end=df['date'].max())

        # Create a template DataFrame with all combinations of categories and date
        unique_categories = [df[cat].unique() for cat in categories]
        all_combinations = product(*unique_categories, date_range)
        template_df = pd.DataFrame(all_combinations, columns=categories + ['date'])

        # Ensure 'date' column in df is in datetime format
        df['date'] = pd.to_datetime(df['date'])
        
        # Merge the template DataFrame with the original DataFrame
        merged_df = template_df.merge(df, on=categories + ['date'], how='left')
        
        for category_values in product(*unique_categories):
            
                filter_condition = np.logical_and.reduce([merged_df[cat] == val \
                    for cat, val in zip(categories, category_values)])
                subset = merged_df.loc[filter_condition].copy()
                
                if subset[value_column].first_valid_index() is not None: 
                    # Add 'day_type' based on the calendar (e.g., weekday, holiday)
                    # Extract year and month from the date column
                    subset['day_type'] = subset['date'].map(
                        lambda date: self.cal.get_day_type_combined(date))
                    subset['year'] = subset['date'].dt.year
                    subset['weeknumber'] = subset['date'].dt.isocalendar().week
                    
                    # Group by year, month, and day_type, then calculate the mean
                    mean_cycle_values = subset.groupby(
                        ['year','weeknumber','day_type'])[value_column].mean().reset_index()
                    # Flatten the multi-index DataFrame
                    mean_cycle_values = mean_cycle_values

                    # Calculate the rolling mean including one month before and after
                    mean_cycle_values[value_column] = mean_cycle_values[value_column]\
                        .rolling(window=5, min_periods=1, center =True).mean()
                    mean_cycle_values[value_column] = mean_cycle_values[value_column].bfill()
                    mean_cycle_values = mean_cycle_values.reset_index()

                    # Merge back the average values to main df and fill NaN values
                    subset = pd.merge(subset, mean_cycle_values,
                                      on=['year', 'day_type', 'weeknumber'],
                                      how='left', suffixes=('', '_mean'))
                    subset['daily_value'] = subset['daily_value'].fillna(
                        subset[value_column+ '_mean'])

                    # Optionally, if you don't want to keep the extra column:
                    subset = subset.reset_index()
                    subset.drop(columns=[value_column+'_mean','year','weeknumber',
                                            'day_type','index'], inplace=True)
        
                    filled_df = pd.concat([filled_df, subset])

        filled_df = filled_df.reset_index(drop = True)
        
        return filled_df


if __name__ == "__main__":
    """Test and example usage of the class
    """
    count = TrafficCounts()
    print("Alpha: \n", count.get_daily_scaling_factors(date = '2022-12-01'))
    print("Gamma: \n", count.get_vehicle_share(date = '2022-12-01'))
    print("Beta: \n", count.get_hourly_scaling_factors('2022-12-01'))
