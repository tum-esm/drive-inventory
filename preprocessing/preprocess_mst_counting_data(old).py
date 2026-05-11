#!/usr/bin/env python
# coding: utf-8

# 
# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Ali Ahmad Khan & Daniel Kühbacher<br>
# **Date:**  27.3.2025
# 
# --- 
# 
# # LHM Counting Data processing
# 
# This script loads the 'Jahresexport_MST_Detektoren*.csv', 'Q*_2019.csv' files, cleans the dataset and converts the data into a predetermined data model. Only the sensors present in 'mst_locations_selected.gpkg' are worked upon<br>
# 
# **Required steps**
# - Import file and convert columns to meaningful datatypes
# - Delete meaningsless columns and rows for detectors not included in locations
# - Convert the ART column into given vehicle classes
# - Merge counting data with location data 

# In[7]:


import sys
import glob
import numpy as np
import pandas as pd
import geopandas as gpd

# import custom modules
from utils import data_paths


# ### Import and Clean raw data from *.csv file

# In[76]:

def run():

    # path to mst counting data
    data_path = data_paths.MST_COUNTING_PATH

    try:
        # read the MST Locations geo packaged file
        mst_loc = gpd.read_file(data_path+'mst_locations_selected.gpkg')
    except Exception as e:
        print("Could not read the MST locations geo packaged file")
        return False

    # list of file patterns to match
    file_patterns = ['Quartalsexport_MST_Detektoren*.csv']
    # Initializes an empty DataFrame
    mst_raw_combined_df = pd.DataFrame()

    try:
        # Iterates over each file pattern
        for file_pattern in file_patterns:

            # gets a list of file paths that match the pattern
            file_paths = glob.glob(data_path + file_pattern)

            # Iterates over the file paths and read each CSV file
            for file_path in file_paths:
                # Specifying data types for columns while reading a CSV file
                df = pd.read_csv(file_path, delimiter=';', decimal=',', encoding='ISO-8859-1')

                # rename the columns of the all dfs retrived to match the first df retrieved
                if not mst_raw_combined_df.empty:
                    df = df.rename(index=str, columns=dict(zip(df.columns.to_list(),
                                                            mst_raw_combined_df.columns.to_list())))

                # concat the dataframes to contain data of all available years
                mst_raw_combined_df = pd.concat([mst_raw_combined_df, df])
    except Exception as e:
        print("Could not read each file pattern")
        return False
    try:
        # Keep rows only with MST_IDs that are present in out geopackage
        mst_raw_combined_df = mst_raw_combined_df[mst_raw_combined_df['MST'].isin(mst_loc['MST_ID'])]
        # Convert the Datetime format to YYYY-MM-DD
        mst_raw_combined_df['date'] = pd.to_datetime(mst_raw_combined_df['DATUM'],format='%d.%m.%Y')
        # Remove unnecessary columns
        mst_raw_combined_df = mst_raw_combined_df.drop(['DATUM','MST','MQ','Unnamed: 30'], axis = 1)
        # Rename the columns to their english alternatives
        mst_raw_combined_df = mst_raw_combined_df.rename(columns={'DETEKTOR_ID': 'detector_id',
                                                                'TAGES_SUMME': 'daily_value'})
        # convert daily value to float
        mst_raw_combined_df['daily_value'] = mst_raw_combined_df['daily_value'].astype(float)


        # ## Data Transformation
        # 
        # ### Create Datframe for volume of traffic for lhm

        # In[78]:


        # Dict to convert ART volume values to vehicle class
        art_to_vehicle_class = {
                            'QKFZ': 'SUM',
                            'QPKW': 'PC',
                            'QLFW': 'LCV',
                            'QPKWA': 'PC',
                            'QLKWA': 'HGV',
                            'QLKW': 'HGV',
                            'QSATTEL_KFZ': 'HGV',
                            'QBUS': 'BUS',
                            'QKRAD': 'MOT'
                        }

        # create raw volume dataframe 
        mst_raw_volume = mst_raw_combined_df.copy()

        # map the art volume categories to vehicles class
        mst_raw_volume['vehicle_class'] = mst_raw_volume['ART'].map(art_to_vehicle_class)

        # drop the 'ART' column
        mst_raw_volume = mst_raw_volume.drop(['ART'], axis = 1)

        # group by all vehicles classes
        mst_raw_volume = mst_raw_volume.groupby(['date', 'detector_id', 'vehicle_class'], as_index=False).sum()

        # assign the detectors their type
        mst_raw_volume['detector_type'] = np.where(mst_raw_volume['vehicle_class'].isna(), 'NaN', '8+1')

        # create a metric column with volume value 
        mst_raw_volume['metric'] = 'volume'


        # ### Create Datframe for speed of traffic for lhm

        # In[79]:


        # Dict to convert ART speed values to vehicle class
        # only consider personal car speed as it is assumed to be representative for all vehicle classes within the city
        art_to_vehicle_class = {'VPKW': 'PC',
                                #'VSPKW': 'SPC',
                                'VLKW' : 'HGV',
                                #'VSLKW' : 'SHGV', 
                                'VKFZ': 'VKFZ'}
                                #'BELPRZ': 'BELPRZ', 
                                #'SLKW' : 'SLKW',
                                #'SPKW':'SPKW'}


        # create raw speed dataframe 
        mst_raw_speed = mst_raw_combined_df.copy()

        # map the art speed categories to vehicles class
        # drop nan vehicle class type rows
        mst_raw_speed['vehicle_class'] = mst_raw_speed['ART'].map(art_to_vehicle_class)
        mst_raw_speed = mst_raw_speed.dropna( subset=['vehicle_class'], axis = 0)

        # map the art speed categories to vehicles class
        mst_raw_speed = mst_raw_speed.drop(['ART'], axis = 1)

        # group by all vehicles classes
        mst_raw_speed = mst_raw_speed.groupby(['date', 'detector_id', 'vehicle_class'], as_index=False).mean(numeric_only=True)

        # assign the detectors their type
        mst_raw_speed['detector_type'] = np.where(mst_raw_speed['vehicle_class'].isna(), 'NaN', '8+1')

        # reset daily volume values as they are not representative and might be misleading
        mst_raw_speed['daily_value'] = 0

        # create a metric column with speed value 
        mst_raw_speed['metric'] = 'speed'


        # ### Concatenate the volume and speed dataframes for lhm & Merge with location data

        # In[80]:


        # Concat the volume and speed dataframes together
        mst_concat = pd.concat([mst_raw_speed, mst_raw_volume])

        # Join the mst_concate dataframe with the locations data
        mst_preprocessed = mst_concat.merge(mst_loc, how = 'left', left_on = 'detector_id', right_on = 'DETEKTOR_ID')

        # Ordered the columns into predetermined order
        mst_preprocessed = mst_preprocessed[['date','road_link_id','detector_id',
                                            'detector_type','vehicle_class','metric','daily_value',
                                            "00:00-01:00", '01:00-02:00', '02:00-03:00', '03:00-04:00',
                                            '04:00-05:00', '05:00-06:00', '06:00-07:00', '07:00-08:00',
                                            '08:00-09:00', '09:00-10:00', '10:00-11:00', '11:00-12:00',
                                            '12:00-13:00', '13:00-14:00', '14:00-15:00', '15:00-16:00',
                                            '16:00-17:00', '17:00-18:00', '18:00-19:00', '19:00-20:00',
                                            '20:00-21:00', '21:00-22:00', '22:00-23:00', '23:00-24:00']]

        # rename the hour columns to be easier indexable
        mapping = {mst_preprocessed.columns[7+i]: str(i) for i in range(0,24)} 
        mst_preprocessed = mst_preprocessed.rename(columns = mapping)


        # ## Store as Parquet File

        # In[84]:


        # Store the dataframe as a parquet file
        mst_preprocessed.to_parquet(data_path+'preprocessed_lhm_counting_data_until2024.parquet', index=False)
    except Exception as e:
        print("Could not process the MST counting data")
        return False
    return True

