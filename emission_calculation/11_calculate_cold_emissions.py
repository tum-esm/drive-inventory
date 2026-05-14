#!/usr/bin/env python
# coding: utf-8

# 
# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Daniel Kühbacher<br>
# **Date:**  16.01.2024
# 
# --- 
# 
# # Calculate Cold Start Excess Emissions (CSEE)
# 
# <!--Notebook description and usage information-->
# This notebook is used to calculate cold start excess emissons using HBEFA emission factors. <br>
# Cold start excess emissions refer to the increased release of pollutants that occur when an engine is started from a cold state, typically when it hasn't been running for several hours. During this phase, the engine and exhaust system are not yet at optimal operating temperatures, which impairs combustion efficiency and the effectiveness of emission control devices like catalytic converters, leading to higher levels of pollutants such as carbon monoxide, hydrocarbons, and nitrogen oxides. These emissions are significantly reduced once the engine warms up.<br>
# 
# HBEFA provides emission factors for Personal Cars (PC) and Light Cargo Vehicles (LCV) in the unit *"gramm/start"*.<br>
# The following parameters can be set:
# - Ambient temperature 
# - Trip length 
# - Parking hours (to determine how hot the engine is before the starting process)
# 
# Since city-specific information on trip lenght or parking hours is generally not available, average values for these parameters are provided as well. Temperature information can be retrieved from local weather stations.
# 
# ## Required input
# - Total number daily vehicle starts in the area of interest. This information can be found in traffic models as it constitutes a major input parameter for traffic modeling.
# - Hourly ambient temperature for the region of interest.
# - Temporal activity profile for extrapolation of the dialy vehicle starts to the whole year
# 
# ## Output
# Total vehicle cold start excess emissions for the area and timeframe of interest. 
# 
# 

# In[ ]:


# import libraries
import sys
import os
os.environ['USE_PYGEOS'] = '0'

import pandas as pd
import geopandas as gpd

# import custom modules
#sys.path.append('../utils')
from utils import data_paths, traffic_counts, hbefa_cold_emissions
from lmu_meteo_api.interface import meteo_data

from datetime import datetime

# Reload local modules on changes
#get_ipython().run_line_magic('reload_ext', 'autoreload')
#get_ipython().run_line_magic('autoreload', '2')


# # Notebook Settings
def run():
# In[ ]:


    # emission components to be calculated
    components = ['CO', 'NOx','NO2', 'CH4', 'CO2(rep)', 'CO2(total)',
                'PM10-ex','BC-ex', 'PM2.5-ex']

    # Define start and end time for emission calculation
    year = 2024
    start_date = datetime(year, 1, 1, 0, 0)
    end_date = datetime(year, 12, 31, 23, 59)

    # define filename of the visum file
    visum_filename = "visum_links.GPKG"

    # if True, the script will only calculate the emission for the area within the roi polygon
    clip_to_area = True
    roi_polygon = data_paths.MUNICH_BOARDERS_FILE # defines ROI for clipping

    # defines the scaling road type for temporal extrapolation
    reference_scaling_road_class = 'Distributor/Secondary'

    ###
    #
    # STORE RESULTS
    #
    ###
    # store spatial results
    store_result = True
    store_path = data_paths.INVENTORY_PATH
    def store_filename(year:str):
        return f'test_hbefa5.1_{year}_cold.gpkg'

    # store temporal profiles
    store_temporal_profiles = False
    store_path_profiles = data_paths.INVENTORY_PATH  + '/temporal_profiles/'
    def store_temporal_profiles_filename(year:str):
        return f'hbefa5.1_{year}_csee_temporal_profiles.gpkg'


    # ## Import data

    # In[ ]:


    # import visum O-D matricies
    visum_links = gpd.read_file(data_paths.VISUM_FOLDER_PATH + visum_filename,
                                driver = 'GPKG')

    # calculate starts per squaremeter before gridding
    visum_links['PC_starts_per_meter'] = visum_links['PC_cold_starts'] / visum_links['geometry'].length
    visum_links['LCV_starts_per_meter'] = visum_links['LCV_cold_starts'] / visum_links['geometry'].length

    if clip_to_area:
        roi = gpd.read_file(roi_polygon).to_crs(visum_links.crs)
        visum_links = gpd.clip(visum_links, roi)
        visum_links = visum_links.explode(ignore_index=True) # convert multipolygons to polygons


    # ## Notebook functions

    # In[ ]:


    # function to generate annual temperature profile from lmu meteo data in Munich
    def annual_temperature_profile(start_date:datetime, 
                                end_date:datetime,
                                aggregate = 'h') -> pd.Series:
        """Downloads meteo data from the LMU Meteo station and returns a dataframe 
        with hourly temperatures for Munich

        Args:
            year (int): Year
            aggregate (str, optional): aggregate to specified timeframe. Defaults to 'H'.

        Returns:
            pd.Series: temperature profile
        """

        start_time = start_date.strftime('%Y-%m-%d') + 'T00-00-00'
        end_time = end_date.strftime('%Y-%m-%d') + 'T23-59-59'

        if datetime.strptime(end_time, '%Y-%m-%dT%H-%M-%S').date() > datetime.now().date():
            end_time = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')

        lmu_met = meteo_data()
        data = lmu_met.get_meteo_data(parameters = ["air_temperature_2m"], 
                                    station_id = 'MIM01', 
                                    start_time = start_time, 
                                    end_time = end_time)

        return (data.air_temperature_2m - 273.15).resample(aggregate).mean().interpolate('linear') # interpolate missing values


    # ## Initialize objects and download temperature data

    # In[ ]:


    # import trafic data, download temperature data and instatiate cold start emission object

    # instanciate traffic count object
    cycles = traffic_counts.TrafficCounts()

    # download temperature data 
    temperature = annual_temperature_profile(start_date=start_date,
                                            end_date=end_date)


    # In[ ]:


    # instanciate cold start emission object
    cs_obj = hbefa_cold_emissions.HbefaColdEmissions(components=components, year=str(year))


    # ## Calculate total emissions for Munich

    # In[ ]:


    # caclulate daily total cold start emissions based on ambient temperature

    # prepare parameters for emission calculation
    parameters = pd.DataFrame(index = pd.date_range(start = start_date,
                                                    end = end_date,
                                                    freq='1h'))
    parameters['temperature'] = temperature
    parameters['hour_factor_PC'] = cycles.timeprofile[reference_scaling_road_class]['PC']
    parameters['hour_factor_LCV'] = cycles.timeprofile[reference_scaling_road_class]['LCV']

    #calculate daily coldstarts in Munich
    daily_PC_starts = (visum_links['PC_starts_per_meter'] * visum_links.length).sum()
    daily_LCV_starts = (visum_links['LCV_starts_per_meter'] * visum_links.length).sum()

    em_list_pc = list()
    em_list_lcv = list()

    PC_result = pd.DataFrame()
    LCV_result = pd.DataFrame()

    for idx, row in parameters.iterrows():
        # get emission factors
        em_PC = cs_obj.calculate_emission_hourly(vehicle_starts = 1,
                                                hourly_temperature=row['temperature'],
                                                vehicle_class='PC',
                                                year = idx.year)
        em_LCV = cs_obj.calculate_emission_hourly(vehicle_starts = 1,
                                                hourly_temperature=row['temperature'],
                                                vehicle_class = 'LCV',
                                                year = idx.year)
        # hourly number of vehicle starts
        hourly_PC_starts = daily_PC_starts * row['hour_factor_PC']
        hourly_LCV_starts = daily_LCV_starts * row['hour_factor_LCV']
        PC_result = pd.concat([PC_result, (em_PC * hourly_PC_starts)], axis=1)
        LCV_result = pd.concat([LCV_result, (em_LCV * hourly_LCV_starts)], axis=1)

    PC_result = PC_result.transpose().set_index(pd.date_range(start=start_date,
                                                    end = end_date,
                                                    freq='1h'))
    LCV_result = LCV_result.transpose().set_index(pd.date_range(start=start_date,
                                                    end = end_date,
                                                    freq='1h'))   
    LCV_result['vehicle_class'] = 'LCV'
    PC_result['vehicle_class'] = 'PC'

    # combine results
    cold_start_emissions = pd.concat([PC_result, LCV_result], axis = 0)
    cold_start_emissions_aggregated = cold_start_emissions.groupby(['vehicle_class'])\
        .resample('1YE').sum(numeric_only = True)
    cold_start_emissions_aggregated = cold_start_emissions_aggregated[components]


    # ## Distribute emissions on VISUM model

    # In[ ]:


    # distribute cold start emissions on road links

    visum_cold_start = visum_links[['PC_cold_starts', 'LCV_cold_starts', 'geometry']].copy()
    visum_cold_start['PC_cold_starts_norm'] = visum_cold_start['PC_cold_starts'].divide(visum_cold_start['PC_cold_starts'].sum())
    visum_cold_start['LCV_cold_starts_norm'] = visum_cold_start['LCV_cold_starts'].divide(visum_cold_start['LCV_cold_starts'].sum())

    visum_cold_start_dict = dict()


    for year in [str(year) for year in range(start_date.year, end_date.year + 1)]: 
        for c in components:
            visum_cold_start[f'PC_{c}'] = visum_cold_start['PC_cold_starts_norm']\
                .mul(cold_start_emissions_aggregated.loc['PC', year].iloc[0][c])
            visum_cold_start[f'LCV_{c}'] = visum_cold_start['LCV_cold_starts_norm']\
                .mul(cold_start_emissions_aggregated.loc['LCV', year].iloc[0][c])

            visum_cold_start_dict.update({year: visum_cold_start.copy()})


    # ## Store spatial results

    # In[ ]:


    # only if store_result is True

    if store_result:
        for year, emissions in visum_cold_start_dict.items():
            visum_cold_start_save = emissions.drop(['PC_cold_starts', 'LCV_cold_starts',
                                                    'LCV_cold_starts_norm', 'PC_cold_starts_norm'], axis = 1)
            # divide by length to get emissions per km
            _col = visum_cold_start_save.drop('geometry', axis = 1).columns
            visum_cold_start_save[_col] = visum_cold_start_save[_col].divide(visum_cold_start_save.geometry.length*1e-3, axis = 0)

            visum_cold_start_save.to_file(store_path + store_filename(year), driver='GPKG')


    # ## Store temporal profiles

    # In[ ]:


    pd.DataFrame(columns = ["year","component","timestamp","scaling_factor"])

    if store_temporal_profiles: 
        for year in [str(year) for year in range(start_date.year, end_date.year + 1)]:
            csee_total = PC_result + LCV_result
            csee_normalized = (csee_total.loc[str(year)]/ csee_total.loc[str(year)].mean(numeric_only=True))[components]
            csee_long = csee_normalized.reset_index().melt(id_vars = 'index')
            csee_long.insert(0, 'year', csee_long['index'].dt.year)
            csee_long.rename(columns = {'variable': 'component', 
                                        'index': 'timestamp',
                                        'value': 'scaling_factor'}, inplace = True)
            csee_long = csee_long[['year', 'component', 'timestamp', 'scaling_factor']]
            csee_long.to_csv(store_path_profiles + store_temporal_profiles_filename(year), index = False)

