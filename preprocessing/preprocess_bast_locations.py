#!/usr/bin/env python
# coding: utf-8

# 
# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Daniel Kühbacher<br>
# **Date:**  30.10.2023
# 
# --- 
# 
# # BAST Location processing
# 
# This notebook preprocessed the location information of the BAST traffic counting stations in Bavaria. 
# 
# The raw data was retrieved manually from:
# https://www.bast.de/DE/Verkehrstechnik/Fachthemen/v2-verkehrszaehlung/Daten/2020_1/Jawe2020.html;jsessionid=B7EAB647A5E95B1101BAD1A925FF188C.live21304?cms_map=1&cms_filter=true&cms_jahr=Jawe2020&cms_land=9&cms_strTyp=&cms_str=&cms_dtvKfz=&cms_dtvSv=
# 
# **Required steps**
# - Import file and convert columns to meaningful datatypes
# - Divide location (represented as single point) into two points for both directions since for
#   motorways, each direction is represented as indiviudal road link.
# 
# **Following steps should be done manually in QGIS**
# - delete useless stations outside the area of interest
# - assign each detector to the street link
# In[1]:
import sys
import pandas as pd
import geopandas as gpd

# import custom modules
from utils import data_paths

def run():
    # In[2]:

    data_path = data_paths.BAST_COUNTING_PATH


    # ## Import and clean raw data from *.csv file

    # In[ ]:
    try:
        # import raw bast location data
        bast_raw = pd.read_csv(data_path+'bast_locations_bavaria.csv', 
                            delimiter=';', decimal = ',', encoding='ISO-8859-1')
    except Exception as e:
        print("Could not read raw bast location data")
        return False

    try:
        # only use 8+1 counters
        bast_loc = bast_raw[bast_raw['Erf_Art']== '8+1']

        # define relevant columns
        relevant_columns = ['DZ_Nr', 'Hi_Ri1', 'Hi_Ri2',
                            'Koor_WGS84_N', 'Koor_WGS84_E']

        bast_loc = bast_loc[relevant_columns]
        bast_loc.head()


        # In[ ]:


        # divide location data into two directions
        columns = ['MST_ID', 'DETEKTOR_ID', 'FAHRTRICHTUNG', 
                'LONGITUDE', 'LATITUDE']
        row_lst = []

        def coordinate_offset(direction, lon, lat): 
            offset = 0.0005
            match direction:
                case 'N':
                    return {'LONGITUDE': lon, 
                            'LATITUDE' : lat+offset}
                case 'O':
                    return {'LONGITUDE': lon-offset, 
                            'LATITUDE' : lat}
                case 'S':
                    return {'LONGITUDE': lon, 
                            'LATITUDE' : lat-offset}
                case 'W':
                    return {'LONGITUDE': lon+offset,
                            'LATITUDE' : lat}

        for idx,row in bast_loc.iterrows():
            row_dict_R1 = { 'MST_ID': row['DZ_Nr'],
                            'DETEKTOR_ID': int(str(row['DZ_Nr']) + '1'),
                            'FAHRTRICHTUNG': row['Hi_Ri1']}

            row_dict_R2 = { 'MST_ID': row['DZ_Nr'],
                            'DETEKTOR_ID': int(str(row['DZ_Nr']) + '2'),
                            'FAHRTRICHTUNG': row['Hi_Ri2']}

            row_dict_R1.update(coordinate_offset(direction = row['Hi_Ri1'],
                                                lon = row['Koor_WGS84_N'],
                                                lat = row['Koor_WGS84_E']))

            row_dict_R2.update(coordinate_offset(direction = row['Hi_Ri2'],
                                                lon = row['Koor_WGS84_N'],
                                                lat = row['Koor_WGS84_E']))

            row_lst.append(row_dict_R1)
            row_lst.append(row_dict_R2)

        bast = pd.DataFrame(row_lst, columns = columns)
        bast.head()


        # # Save preprocessed bast locations as *.gpkg

        # In[5]:


        bast = gpd.GeoDataFrame(
            bast, geometry=gpd.points_from_xy(bast.LATITUDE, bast.LONGITUDE))
        bast.drop(['LATITUDE', 'LONGITUDE'], axis = 1, inplace = True)
        bast = bast.set_crs(epsg='4326')

        # save data
        bast.to_file(data_path + "bast_locations_cleaned.gpkg", driver="GPKG")
    except Exception as e:
        print("Could not process bast locations")
        return False

    return True
if __name__ == "__main__":
    run()   