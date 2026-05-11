#!/usr/bin/env python
# coding: utf-8

# 
# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Ali Ahmad Khan & Daniel Kühbacher<br>
# **Date:**  27.03.2025
# 
# --- 
# 
# # BAST Counting Data processing
# 
# This script loads the 'BAST_CountingStations_daily.csv' files, cleans the dataset and converts the data into a predetermined data model. Only the sensors present in 'bast_locations_selected.gpkg' are worked upon<br>
# 
# **Required steps**
# - Import file and convert columns to meaningful datatypes
# - Delete meaningsless columns and rows for detectors not included in locations
# - Convert the format from wide to long table and pivot to achieve the data model
# - Merge Counting Data with location data

# In[1]:


import sys
import pandas as pd
import geopandas as gpd
import numpy as np

# import custom modules
from utils import data_paths


# ## Import and Clean raw data from the *.csv file

# In[2]:

def run():

    # path to the folder for BAST data
    data_path = data_paths.BAST_COUNTING_PATH
    try:
        # read bast location geopackaged file
        bast_loc = gpd.read_file(data_path+'bast_locations_selected.gpkg')
    except Exception as e:
        print("Could not read bast location geopackaged file")
        return False

    try:
        # Reads Bast Counting data from the csv file
        bast_raw = pd.read_csv(data_path+'BAST_CountingStations_daily_until2024.csv', 
                            delimiter=',', decimal = ';', encoding='ISO-8859-1', index_col =0)
    except Exception as e:
        print("Could not read Bast counting data")
        return False

    try:
        # converts the time into datetime format YYYY-MM-DD
        bast_raw['date'] = pd.to_datetime(bast_raw['Datum'],format='%y%m%d')

        # Remove all columns that start with K_
        bast_raw = bast_raw[bast_raw.columns[~bast_raw.columns.str.startswith('K_')]]

        # Remove the named unnecessary column
        bast_raw = bast_raw.drop(['TKNR','Datum', 'Land', 'Strklas', 'Strnum', 'Wotag',
                                'Fahrtzw','PLZ_R1','PLZ_R2','Lkw_R1','Lkw_R2'], axis = 1)


        # ## Data transormation
        # 
        # ### Create DataFrame with rows for each detector id

        # In[3]:


        # Keep rows only with Zst that are present in geopackage dataframe
        bast_raw = bast_raw.loc[bast_raw['Zst'].isin(bast_loc['MST_ID'].unique())]

        # Filter out the columns ending in R2 for df_r1 and vice versa for df_r2
        df_r1 = bast_raw[bast_raw.columns[~bast_raw.columns.str.endswith('R2')]].copy()
        df_r2 = bast_raw[bast_raw.columns[~bast_raw.columns.str.endswith('R1')]].copy()

        # Add suffix 1 and 2 to 'Zst' column for each DataFrame to create detector id
        df_r1['detector_id'] = df_r1['Zst'].astype(str) + '1'
        df_r2['detector_id'] = df_r2['Zst'].astype(str) + '2'

        # Remove the '_R1' suffix from df_r1 columns
        df_r1.columns = df_r1.columns.str.replace('_R1$', '', regex=True)

        # Remove the '_R2' suffix from df_r2 columns
        df_r2.columns = df_r2.columns.str.replace('_R2$', '', regex=True)

        # concatenate the dataframes with r1 and r2 columns
        transformed_bast_df = pd.concat([df_r1,df_r2])


        # ### Create a dataframe with per hour column

        # In[5]:


        # Id VAriable to be used for melt
        id_vars = ['Zst','date','detector_id','Stunde']

        # Melting the dataframe to have vehicle types and their counts
        melted_bast_df = transformed_bast_df.melt(id_vars= id_vars,
                            value_vars= transformed_bast_df.columns.difference(id_vars),
                            var_name='vehicle_class',
                            value_name='vehicle_count')

        # Pivot the table in regards to Stunde column
        pivoted_bast_df = pd.pivot_table( 
                                    melted_bast_df,
                                    values='vehicle_count',
                                    index=['Zst','date', 'detector_id','vehicle_class'],
                                    columns=['Stunde'],
                                    aggfunc="sum"
                                    ).reset_index().rename_axis(None, axis=1)

        # Dict to convert BAST vehicle classes to predetermined classes 
        vehicle_class = {
                        'KFZ': 'SUM',
                        'Pkw': 'PC',
                        'PmA': 'PC',
                        'Lfw': 'LCV',
                        'Lzg': 'HGV',
                        'LoA': 'HGV',
                        'Bus': 'BUS',
                        'Mot': 'MOT',
                        }

        # Map the classes
        pivoted_bast_df['vehicle_class'] = pivoted_bast_df['vehicle_class'].map(vehicle_class)

        # FIll na and also assignd int to column
        pivoted_bast_df['detector_id'] = pivoted_bast_df['detector_id'].fillna(0).astype(int)

        # Assings all columns as float type for all stunde
        for col in range(1, 25):
            pivoted_bast_df[col] = pivoted_bast_df[col].fillna(0).astype(float)

        # Group by the data  and sum it all up for given vehicle classes
        pivoted_bast_df = pivoted_bast_df.groupby(['Zst', 'date', 'detector_id','vehicle_class'],
                                                as_index=False).sum()

        # Assign detector type
        pivoted_bast_df['detector_type'] = np.where(pivoted_bast_df['vehicle_class'].isna(),
                                                    'NaN', '8+1')

        # Create a daily_value column that sums up data for all hours
        pivoted_bast_df['daily_value'] = pivoted_bast_df.loc[:, 1:24].sum(axis=1)

        # Assign the metric with volume value
        pivoted_bast_df['metric'] = 'volume'


        # ## Merge Dataframe with location data

        # In[6]:


        # Merge the processed bast data with bast location
        processed_bast_df = pivoted_bast_df.merge(bast_loc, how = 'left', left_on = 'detector_id', right_on = 'DETEKTOR_ID').copy()

        # Assign a predetermined order to the columns
        column_order = ['date', 'road_link_id', 'detector_id', 'detector_type',
                        'vehicle_class','metric', 'daily_value'] + [i for i in range(1, 25)]
        processed_bast_df = processed_bast_df[column_order]

        # rename hour columns to match hour schema 0-23
        processed_bast_df = processed_bast_df.rename({i:(i-1) for i in range(1,25)}, axis = 'columns')


        # ## Store as Parquet File

        # In[9]:


        # Convert all columns to string to parquet storage
        processed_bast_df.columns = processed_bast_df.columns.astype(str)

        # Store the dataframe as a parquet file
        processed_bast_df.to_parquet(data_path+'preprocessed_bast_counting_data_until2024.parquet', index=False)
    except Exception as e:
        print("Could not process bast counting data")
        return False
    return True

