#!/usr/bin/env python
# coding: utf-8

# 
# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Daniel Kühbacher<br>
# **Date:**  26.10.2023
# 
# --- 
# 
# # MST Location processing
# 
# This script loads the 'mst-locations.csv', cleans the dataset and converts the geoinformation to a geopackage file. The MST locations were provided by the City of Munich, however, they were not used in a GIS application before.<br>
# 
# **Required steps**
# - Import file and convert columns to meaningful datatypes
# - Delete meaningsless locations/ coordinates
# 
# **Following steps should be done manually in QGIS**
# - delete useless stations (e.g. many stations arount the fair area or next to allianz arena)
# - cross check the detector positions with the location details and assign each detector to the street link

# In[1]:


import sys
import math
import pandas as pd
import geopandas as gpd

from utils import data_paths

def run():
    # In[2]:


    # path to mst counting data
    data_path = data_paths.MST_COUNTING_PATH


    # ## Import and clean raw data from *.csv file

    # In[ ]:

    try:
        mst_loc = pd.read_csv(data_path + "mst-locations.csv", delimiter = ";", decimal=",")
    except Exception as e:
        print(f"Error occurred while reading MST location data: {e}")
        return False
    try:
        mst_loc.drop(['XKOOR', 'YKOOR', 'Unnamed: 8'], axis = 1, inplace= True)
        mst_loc["LONGITUDE"] = pd.to_numeric(mst_loc["LONGITUDE"], errors='coerce') 
        mst_loc["LATITUDE"] = pd.to_numeric(mst_loc["LATITUDE"], errors='coerce') 


        # Some detector locations miss the geoinformation. 
        # Therfore, they will be updated with the mean location of the remaining detectors 
        # and then assigned to the right road link in QGIS.

        # detectors with missing geoinformation
        mst_missing_loc = mst_loc[(mst_loc['LONGITUDE']<10) | (mst_loc['LONGITUDE']>13)]

        # calculate mean location for all stations without missing geoinformation
        mst_mean_location = mst_loc.drop(mst_missing_loc.index, axis = 0)
        mst_mean_location = mst_mean_location.groupby('MST_ID').mean(numeric_only = True)

        # add mean location to the missing locations in the locations dataframe
        for idx, row in mst_missing_loc.iterrows():
            try:
                lon = mst_mean_location.loc[row['MST_ID']]['LONGITUDE']
                lat = mst_mean_location.loc[row['MST_ID']]['LATITUDE']
                mst_loc.at[idx, 'LONGITUDE'] = lon
                mst_loc.at[idx, 'LATITUDE'] = lat
            except: 
                continue

        # drop the stations that still have ivalid locations
        mst_loc.drop(mst_loc[(mst_loc['LONGITUDE']<10) | (mst_loc['LONGITUDE']>13)].index, inplace = True)
        mst_loc.head()


        # ## Convert column "FAHRTRICHTIUNG" to direction abbreviation

        # In[4]:


        #dataset does not contain 'FAHRSPUR Information'
        direction = {'Nord': 'N', "NordWest": "NW", 
                    "West": "W", "SüdWest": "SW", 
                    "Süd": "S", "SüdOst": "SO", 
                    "Ost":"O", "NordOst":"NO", "NEIN":"None"}
        mst_loc['FAHRTRICHTUNG'] = mst_loc.apply(lambda row: direction[row['FAHRTRICHTUNG']], axis = 1)


        # ## Convert to geopackage and save the cleaned mst location data

        # In[5]:


        mst = gpd.GeoDataFrame(
            mst_loc, geometry=gpd.points_from_xy(mst_loc.LONGITUDE, mst_loc.LATITUDE))
        mst.drop(['LONGITUDE','LATITUDE'], axis = 1, inplace = True)
        mst = mst.set_crs(epsg='4326')

        # save data
        mst.to_file(data_path + "mst_locations_cleaned.gpkg", driver="GPKG")
    except Exception as e:
        print(f"Error occurred while processing MST location data: {e}")
        return False

    return True

