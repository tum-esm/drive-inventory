#!/usr/bin/env python
# coding: utf-8

# 
# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Daniel Kühbacher & Ali Ahmad Khan<br>
# **Date:**  27.03.2025
# 
# --- 
# 
# # Combine preprocessed datasets
# 
# This file is to construct a final counting data product that combines different counting data sources, cleanes and aggregates the data and finally adds further information from different sources. The final product can be used in the emission generator pipeline to calculate actual emissions.
# 
# **Required steps**
# - import counting data, the traffic model and the calendar
# - filter for metric "volume"
# - aggregate count data by road links (A single road link could have several detectors on different lanes. These need to be aggregated)
# - add road type information from the traffic model and day type infromation from the calendar
# - Filter for valid rows: check consistency between sum of hourly values and the daily sum and only accept data with daily value > 1; drop ivalid rows
# - Check for the consistency with the visum model -> add flag "valid" if consistent
# - Flag as "incomplete" if there is no data for the timeframe of interest
# - Store as parquet file

# In[1]:


import sys
import pandas as pd
import numpy as np
import geopandas as gpd

from math import sqrt

# import custom modules
from utils import data_paths
from utils import excel_calendar


# ### Import and prepare datasets
# - preprocessed BASt traffic counting data (only traffic volume)
# - preprocessed LHM traffic counting data (traffic volume and speed)
# - traffic model
# - calendar 

    # In[2]:

def run():
    # define file paths
    mst_file_path = data_paths.MST_COUNTING_PATH + 'preprocessed_lhm_counting_data_until2024.parquet'
    bast_file_path = data_paths.BAST_COUNTING_PATH + 'preprocessed_bast_counting_data_until2024.parquet'
    visum_file_path = data_paths.VISUM_FOLDER_PATH + 'visum_links.gpkg'

    try:
        # import and concatenate bast and mst counting data
        counting_data = pd.concat([pd.read_parquet(mst_file_path), 
                                pd.read_parquet(bast_file_path)], axis = 0)
        counting_data = counting_data[counting_data['date'] < '2025-01-01']
        # import visum links data
        visum_links = gpd.read_file(visum_file_path)
    except Exception as e:
        print(f"Error occurred while reading MST counting data, BAST counting data and/or visum traffic model: {e}")
        return False

    try:
        # initialize calendar object
        cal_obj = excel_calendar.Calendar()

        print(f'Number of imported rows in the counting data: {len(counting_data)}')


        # ### Prepare traffic volume dataset
        # First we will filter the data for traffic volume counts and aggregate the single detector values. Then further information is added from the visum model and the calendar.</br>
        # Rows with "none" road types will be dropped since they are not assigned to any road link in the visum model.

        # In[3]:


        # aggregate counts for each road_link_id and reduce to volume dataset
        volume  = counting_data.groupby(['metric','road_link_id',
                                        'vehicle_class', 'date']).sum(numeric_only = True).loc['volume']
        volume = volume.drop(['detector_id'], axis = 1)
        volume = volume.reset_index()

        # add road type information
        road_types = visum_links.set_index('road_link_id')['road_type'].to_dict()
        volume.insert(3,'road_type' , volume['road_link_id'].map(road_types))
        # drop rows with road_type = "none"
        volume = volume[volume['road_type'] != 'none']

        # add day type information
        dates = volume['date'].unique()
        day_types = {date:cal_obj.get_day_type_combined(date) for date in dates}
        volume.insert(4, 'day_type', volume['date'].map(day_types))

        # drop rows with NaN values
        volume = volume.dropna()

        print(f'Number of rows: {len(volume)}')
        print(pd.Series([road_types[i] for i in volume['road_link_id'].unique()]).value_counts())


        # ### Filter for valid rows

        # In[4]:


        # sum of all hour values of the day needs to be consistent with the sum of the day -> error_bound e=5%
        e = 0.025

        # Filter rows based on the condition
        volume_processed = volume[
            volume.iloc[:, 6:].sum(axis=1).between(
                volume['daily_value'] * (1 - e),
                volume['daily_value'] * (1 + e)
            )].copy()

        # drop rows with daily_volume <1
        volume_processed = volume_processed[volume_processed['daily_value'] > 1]

        print(f'Remaining number of rows: {len(volume_processed)}')
        print(pd.Series([road_types[i] for i in volume_processed['road_link_id'].unique()]).value_counts())


        # ### Outlier Detection

        # In[5]:


        # Initialize a new DataFrame to store the outliers
        volume_processed_outliers_df = pd.DataFrame(columns= volume_processed.columns)

        # Define the threshold for modified Z-Score outliers (adjust as needed)
        modified_z_score_threshold = 3.5

        def detect_outliers(group):
            daily_values = group['daily_value']
            median = np.median(daily_values)
            mad = np.median(np.abs(daily_values - median))
            modified_z_scores = np.abs(0.6745 * (daily_values - median) / mad)
            group['is_outlier'] = modified_z_scores > modified_z_score_threshold
            return group

        # Apply the outlier detection function to each group and concatenate the results
        volume_processed_outliers_df = volume_processed.groupby(['road_link_id', 'vehicle_class', 'day_type']).apply(detect_outliers)

        # Reset the index and rename axis to obtain a flat column hierarchy
        volume_processed_outliers_df = volume_processed_outliers_df.reset_index(drop=True)
        volume_processed = volume_processed_outliers_df[volume_processed_outliers_df.is_outlier==False].drop('is_outlier', axis =1)

        print(f'Outlier Number of rows: {len(volume_processed_outliers_df[volume_processed_outliers_df.is_outlier==True])}')
        print(f'Remaining number of rows: {len(volume_processed)}')
        print(pd.Series([road_types[i] for i in volume_processed_outliers_df[volume_processed_outliers_df.is_outlier==False]['road_link_id'].unique()]).value_counts())


        # ### Check for consistency with VISUM model
        # 
        # For 2019 data we can check if the average daily count for weekdays outside the vacation time agrees with the visum model. The SQV (scalable quality value) is used with an f-factor of 10000. This sqv value indicates how well the modeled and observed data agrees while >0.8 is a good fit and >0.6 an acceptable fit. To avoid big influence by outliers, the inter-quantile range mean was selected to aggregate the counting data. 

        # In[6]:


        def iqr_mean(input, iqr_range = (2.5, 97.5)):
            lower_bound = np.percentile(input, iqr_range[0])
            upper_bound = np.percentile(input, iqr_range[1])
            return np.mean(input[(input >= lower_bound) & (input <= upper_bound)])

        def calc_sqv(Observed, Model, f=10000):
            # f = 10000 is the recommended factor for daily volumes 
            return 1/(1 + sqrt(pow( Model - Observed, 2) / (f * Observed)))


        # In[7]:


        cnt_2019 = volume_processed[(volume_processed['date'].between('2019-01-01', '2019-12-31')) &
                                    (volume_processed['day_type'] == 0)]
        mean_cnt_2019 = cnt_2019.groupby(['road_link_id', 'vehicle_class'])['daily_value'].apply(iqr_mean).reset_index()
        mean_cnt_2019 = mean_cnt_2019.pivot(columns = 'vehicle_class', index = 'road_link_id')
        mean_cnt_2019 = mean_cnt_2019.droplevel(0, axis=1)

        #aggregate dtv for each road link of the visum model
        visum_links['dtv_PC'] = visum_links['dtv_SUM'] * visum_links['delta_PC']
        visum_links['dtv_LCV'] = visum_links['dtv_SUM'] * visum_links['delta_LCV']
        visum_links['dtv_HGV'] = visum_links['dtv_SUM'] * visum_links['delta_HGV']
        visum_grp = visum_links.groupby('road_link_id')[['dtv_SUM','dtv_PC','dtv_LCV', 'dtv_HGV']].sum()

        visum_validation = pd.concat([mean_cnt_2019, visum_grp.loc[visum_grp.index.isin(mean_cnt_2019.index)]], axis=1)

        # calculate sqv value for each vehicle class
        for vehicle_class in ['SUM', 'PC', 'LCV', 'HGV']:
            visum_validation['sqv_' + vehicle_class] = visum_validation.apply(
                lambda row: calc_sqv(row[vehicle_class], row['dtv_' + vehicle_class]), axis = 1)


        # In[8]:


        visum_validation[visum_validation['sqv_SUM'] > 0.6].index.nunique()


        # In[9]:


        valid_sqv_threshold = 0.6
        # add sqv value for each vehicle class to the counting dataset

        volume_processed.insert(4,'sqv', 0.0,)

        # add sqv value to dataframe
        for vehicle_class in ['SUM', 'PC', 'LCV', 'HGV']:
            volume_processed.loc[volume_processed['vehicle_class'] == vehicle_class, 'sqv'] = \
                volume_processed.loc[volume_processed['vehicle_class'] == vehicle_class, 'road_link_id']\
                    .map(visum_validation['sqv_' + vehicle_class])

        # add valid column and set to True if sqv > threshold for vehicle class SUM
        volume_processed.insert(4,'valid', False)
        valid_road_links = visum_validation[visum_validation['sqv_SUM'] > valid_sqv_threshold].index.unique()
        volume_processed.loc[volume_processed['road_link_id'].isin(valid_road_links), 'valid'] = True


        # ### Flag incomplete timeseries

        # In[11]:


        time_start = '2019-01-01'
        time_end = '2024-12-31'
        completeness_thres = 0.8

        # find counting stations that cover
        df = volume_processed[(volume_processed['vehicle_class'] == 'SUM') &
                        (volume_processed['date'].between(time_start, time_end))]

        df = df.groupby('road_link_id')['daily_value'].count()
        complete = df/df.max()
        volume_processed.insert(5, 'completness', 0.0)

        # add complete column to the counting dataset
        for idx,row in volume_processed.iterrows():
            try:
                volume_processed.at[idx, 'completness'] = complete[row['road_link_id']]
            except KeyError: 
                volume_processed.at[idx, 'completness'] = 0.0

        volume_processed.insert(4,'complete', volume_processed['completness'].apply(lambda x: True if (x > completeness_thres) or (x==0.0) else False))


        # In[12]:


        df = volume_processed[(volume_processed['vehicle_class']=='SUM')]
        print(f'Number of rows in the dataset : {len(df)}')
        pd.Series([road_types[i] for i in df['road_link_id'].unique()]).value_counts()


        # In[13]:


        df = volume_processed[(volume_processed['vehicle_class']=='SUM') & 
                            (volume_processed['complete'] > 0.8)]
        print(f'Number of rows in the dataset : {len(df)}')
        pd.Series([road_types[i] for i in df['road_link_id'].unique()]).value_counts()


        # In[14]:


        df = volume_processed[(volume_processed['vehicle_class']=='SUM') & 
                            (volume_processed['complete'] > 0.8) &
                            (volume_processed['valid'])]
        print(f'Number of rows in the dataset : {len(df)}')
        pd.Series([road_types[i] for i in df['road_link_id'].unique()]).value_counts()


        # ## Aggregate Road Types
        # Since Access-residential, and TrunkRoad/Primary-National only have < 5 counting stations, they will be merged to Distributor/Secondary road_type.

        # In[15]:


        volume_processed.insert(7, 'scaling_road_type', volume_processed['road_type'])

        volume_processed.loc[volume_processed['scaling_road_type']=='Access-residential', 'scaling_road_type'] = 'Distributor/Secondary'
        volume_processed.loc[volume_processed['scaling_road_type']=='TrunkRoad/Primary-National', 'scaling_road_type'] = 'Distributor/Secondary'


        # ## Store as Parquet File

        # In[16]:


        # path to mst counting data
        data_path = data_paths.COUNTING_PATH

        # Store the dataframe as a parquet file
        volume_processed.to_parquet(data_path+'counting_data_combined_until2024_v2.parquet', index=False)
    except Exception as e:
        print("Something went wrong while trying to combine the preprocessed files.")
        return False
    return True    
