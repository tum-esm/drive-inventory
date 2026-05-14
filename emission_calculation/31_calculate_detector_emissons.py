#!/usr/bin/env python
# coding: utf-8

# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Daniel Kühbacher<br>
# **Date:**  07.05.2024
# 
# --- 
# 
# # Detector Emission Calculation
# 
# <!--Notebook description and usage information-->
# Calculates the traffic volume and the emissions based on the true counting data. This information is used in the uncertainty analysis.
# 

# In[1]:


# import libraries

import sys
import os
os.environ['USE_PYGEOS'] = '0'

import pandas as pd
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt
import seaborn as sns

from datetime import datetime, time

#sys.path.append('../utils')
from utils import data_paths, hbefa_hot_emissions

# Reload local modules on changes
#get_ipython().run_line_magic('reload_ext', 'autoreload')
#get_ipython().run_line_magic('autoreload', '2')


# ## Notebook Settings
def run():
    # In[2]:


    # year of investigation
    year = 2019
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31)

    # Define VISUM filename
    visum_filename = "visum_links.GPKG"

    #Define Counting Data filename
    cnt_data_filename  = data_paths.COMBINED_COUNTING_DATA

    # Define vehicle classes and components
    vehicle_classes = ['PC', 'LCV', 'HGV', 'BUS', 'MOT']
    components = ['CO2(rep)', 'CO2(total)', 'NOx', 'CO']

    ###
    #
    # Save Data as parquet file
    #
    ##

    save_results = True
    save_filepath = data_paths.INVENTORY_PATH + 'DetectorEmissions_2019_vc_estimate.feather'


    # ## Notebook Functions

    # In[3]:


    # calculate emissions based on counting data

    def calculate_emissions(year: int,
                            vehicle_class: str,
                            vehicle_volume: int,
                            TraSit: str,
                            hbefa_gradient: str,
                            component: str, 
                            hbefa_class: hbefa_hot_emissions.HbefaHotEmissions) -> float:
        """Calculates the emissions for a single vehicle class based on the given traffic volume and hbefa Traffic Situation

        Args:
            year (int): Year of investigation
            vehicle_class (str): Vehicle Class
            vehicle_volume (int): Traffic volume of the respective vehicle class
            TraSit (str): Traffic situation 
            hbefa_gradient (str): Road gradient
            component (str): Emission component
            hbefa_class (HbefaHotEmissions): pre-initilized HBEFA object

        Returns:
            float: Emission estimate for the given input parameters
        """

        try:

            ef = hbefa_class.ef_dict['EFA_weighted'][year, 
                                                    TraSit,
                                                    vehicle_class, 
                                                    hbefa_gradient,
                                                    component]

        except KeyError:
            ef = hbefa_class.ef_dict['EFA_weighted'][year, 
                                                    TraSit,
                                                    vehicle_class, 
                                                    '0%',
                                                    component]
        return vehicle_volume * ef


    # ## Import Data

    # In[4]:


    # import visum and couting data and initialize hbefa class

    # import visum file
    visum_links = gpd.read_file(data_paths.VISUM_FOLDER_PATH + visum_filename)

    # import counting data
    cnt_data = pd.read_parquet(cnt_data_filename)

    # subselect counting data for links that are in the visum network
    cnt_data = cnt_data[cnt_data['road_link_id'].isin(visum_links['road_link_id'].unique())]
    cnt_data = cnt_data[cnt_data['date'].between(start_date, end_date)].copy() # reduce to timeframe of interest

    # import hbefa emission module
    hbefa = hbefa_hot_emissions.HbefaHotEmissions()


    # ## Prepare dataframe with road link information for each detector location

    # In[5]:


    # prepare detector information dataframe

    road_info = pd.merge(cnt_data['road_link_id'].drop_duplicates(), visum_links[['road_type', 'hbefa_gradient',
                                        'hbefa_speed', 'speed', 'road_link_id', 'hour_capacity']], 
                        left_on = 'road_link_id', 
                        right_on = 'road_link_id', 
                        how = 'inner')

    # set duplicates in road gradient to 0%
    road_info = road_info.groupby('road_link_id').agg({'speed': 'first', 
                                                    'hbefa_speed': 'first',
                                                    'hour_capacity': 'sum',
                                                    'hbefa_gradient': lambda x: x.iloc[0] if len(x)==1 else '0%'}).reset_index()
    road_info.head()


    # # Prepare counting dataframe for emission calculation

    # In[6]:


    # prepare counting dataframe for emission calculation

    _cnt = cnt_data.melt(id_vars = ['date', 'road_link_id','road_type', 'vehicle_class'],
                        value_vars = [str(x) for x in range(0,24)])

    _cnt['timestamp'] = _cnt.apply(lambda row: pd.Timestamp.combine(row['date'],
                                                                    time(int(row['variable']))), axis =1)

    _cnt = _cnt[_cnt['vehicle_class']!='SUM'] # delete 'SUM' vehicle class

    # prepare volume dataset
    _cnt_volume = _cnt.pivot(index = ['road_link_id', 'road_type', 'timestamp'],
                                    columns = 'vehicle_class',
                                    values = 'value')

    _cnt_volume['SUM_PCU'] = _cnt_volume.mul(pd.Series(hbefa.car_unit_factors)).sum(axis = 1)
    _cnt_volume = _cnt_volume.dropna().reset_index()

    cnt_volume = pd.merge(_cnt_volume, road_info, on = 'road_link_id', how = 'inner')

    # caclulate traffic condition
    cnt_volume['TraSit']= cnt_volume.apply(lambda row: hbefa.calc_los_class(hbefa_speed=row['hbefa_speed'],
                                                                            hour_capacity=row['hour_capacity'],
                                                                            htv_car_unit = row['SUM_PCU'],
                                                                            road_type = row['road_type']),
                                        axis = 1)


    # # Calculate emissions for each detector
    # 

    # In[7]:


    # calculate emissions for each component

    for c in components: 
        for vc in vehicle_classes:
            cnt_volume[f'{vc}_{c}'] = cnt_volume.apply(lambda row: calculate_emissions(year = year,
                                                                                    vehicle_class=vc,
                                                                                    vehicle_volume= row[vc],
                                                                                    TraSit=row['TraSit'],
                                                                                    hbefa_gradient=row['hbefa_gradient'],
                                                                                    component=c,
                                                                                    hbefa_class=hbefa), axis = 1)
    cnt_volume.head()


    # ## Save detector emission results

    # In[8]:


    # only if save_results is True
    if save_results: 
        cnt_volume.to_feather(save_filepath)

