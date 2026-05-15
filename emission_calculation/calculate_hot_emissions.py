#!/usr/bin/env python
# coding: utf-8

# *Technical University of Munich<br>
# Professorship of Environmental Sensing and Modeling<br><br>*
# **Author:**  Daniel Kühbacher<br>
# **Date:**  06.02.2024
# 
# --- 
# 
# # Calculate hot vehicle emissions using HBEFA emission factors
# 
# <!--Notebook description and usage information-->
# This notebook implements the <utls/hot_emission_process.py> function and multiprocessing to calculate hot vehicle emissions for a given area. 
# 

# In[ ]:


# import libraries
import sys
import os
os.environ['USE_PYGEOS'] = '0'

import multiprocessing
import geopandas as gpd
import pandas as pd
from datetime import datetime

#sys.path.append('../utils')
from utils import data_paths, traffic_counts, hbefa_hot_emissions, hot_emission_process

# Reload local modules on changes
#get_ipython().run_line_magic('reload_ext', 'autoreload')
#get_ipython().run_line_magic('autoreload', '2')


# # Notebook Settings
def run():
        # In[ ]:
    try:

        # Define start and end time for emission calculation. Ideally this should cover a whole year.
        year = 2019
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31)

        # define filename of the visum file
        visum_filename = "visum_links.GPKG"

        # if True, the script will only calculate the emission for the area within the roi polygon
        clip_to_area = True
        roi_polygon = data_paths.MUNICH_BOARDERS_FILE # defines ROI for clipping

        # select aggregated or los-specific mode for traffic situation calculation
        #mode = 'aggregated' 
        mode = 'los_specific'

        vehicle_classes = ['PC', 'LCV', 'HGV', 'BUS', 'MOT']
        components = ['HC', 'CO', 'NOx', 'PM', 'PN', 'CO2(rep)',
                    'CO2(total)', 'NO2', 'CH4', 'NMHC', 'PM (non-exhaust)', 'Benzene', 'PM2.5',
                    'BC (exhaust)', 'PM2.5 (non-exhaust)', 'BC (non-exhaust)', 'CO2e']

        # Choose emission type: Tank-To-Wheel, Well-To-Tank (WTT), Well-To-Wheel (WTW)
        # WTW includes upstream emisssions from fuel production and distribution
        emission_type = 'EFA_weighted'
        #emission_type = 'EFA_WTT_weighted'
        #emission_type = 'EFA_WTW_weighted'

        # if True, the timeprofiles for the selected components will be calculated
        calculate_timeprofile = False
        store_timeprofiles = False

        # define number of processes for multiprocessing
        NUMBER_OF_PROCESSES = 7

        ###
        #
        # STORE RESULTS
        #
        ###

        store_results = True
        store_filename = f'linesource_Munich_{year}_los_specific.gpkg'


        # ## Import Data and Initialize Objects

        # In[ ]:


        # import visum model
        visum = gpd.read_file(data_paths.VISUM_FOLDER_PATH + visum_filename)

        if clip_to_area:
            roi = gpd.read_file(roi_polygon).to_crs(visum.crs)
            visum = gpd.clip(visum, roi)
            visum = visum.explode(ignore_index=True) # convert multipolygons to polygons

        #visum = visum_links
        visum = visum.reset_index(drop = True).reset_index() # reset index for calculation

        # initialize traffic cycles
        cycles = traffic_counts.TrafficCounts()
        # initialize HBEFA emission factors
        hbefa = hbefa_hot_emissions.HbefaHotEmissions(components= components, 
                                vehicle_classes= vehicle_classes, 
                                ef_type= emission_type,
                                year= str(year))

        perturbation_factor = 1.1 # apply a uniform perturbation factor to all hbefa service thresholds

        # define hbefa service thresholds
        default_vcr = hbefa.default_vcr_thresholds
        changed_vcr = {k: [round(v * perturbation_factor, 5) for v in vals] for k, vals in default_vcr.items()}

        # apply service thresholds as defined in the notebook setting
        hbefa.vcr_thresholds = changed_vcr


        # ## Process Inventory
        # Use multiprocessing to calculate the emission for each road link day by day. This process will take some time to be finished for the whole area of interest.

        # In[ ]:


        # calculate emission for each day

        dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(start = start_date,
                                                            end = end_date,
                                                            freq = '1d')]

        with multiprocessing.Manager() as manager: 

            result_queue = manager.Queue()
            error_queue = manager.Queue()

            with multiprocessing.Pool(NUMBER_OF_PROCESSES) as pool:
                parameters = [(d,
                            mode,
                            visum.to_dict('records'),cycles,
                            hbefa,
                            result_queue,
                            error_queue,
                            ) for d in dates]

                res = pool.starmap(hot_emission_process.process_daily_emissions, parameters)

            # concatenate final process results.
            result = result_queue.get() #get first result from queue
            while not result_queue.empty():
                print('Concatenate final process results')
                new_result = result_queue.get()
                for road_index, emissions in result.items():
                    for component, value in emissions.items():
                        add_emissions = new_result[road_index][component]
                        result[road_index][component] += add_emissions

            # retrieve process errors
            errors = list()
            while not error_queue.empty(): 
                errors.append(error_queue.get())


        # In[ ]:


        # print errors
        for e in errors:
            print (e)


        # ## Concatenate Results
        # All results are saved in result dict. This can be appended to the traffic model. 

        # In[ ]:


        # concatenate results and append to visum dataframe

        result_df = pd.DataFrame(result).transpose()
        result_df.columns = result_df.columns.map('_'.join)
        visum_result = pd.concat([visum, result_df], axis = 1)


        # ## Store results

        # In[ ]:


        # only if store_results is True

        if store_results: 
            path = data_paths.INVENTORY_PATH
            visum_result.to_file(path + store_filename, driver='GPKG')


        # ## Calculate and Save Timeprofiles

        # In[ ]:


        # only if store_result = True
        if calculate_timeprofile: 

            # timeframe of interest
            dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(start = start_date,
                                                                end = end_date,
                                                                freq = '1d')]

            #placeholder for raw temporal profile
            raw_profile = pd.DataFrame()
            for day in dates:
                em_dict = hot_emission_process.process_hourly_emissions(day,
                                                visum[visum['road_type'] != 'Access-residential'].to_dict('records'), # reduce complexity
                                                cycles,
                                                hbefa)

                em_sum = pd.DataFrame(em_dict).sum(axis = 1).reset_index()
                em_sum.columns = ['vehcat', 'component', 'hour', 'emission']
                em_fin = em_sum.groupby(['component', 'hour']).sum(numeric_only=True).reset_index()
                em_fin['date'] = day
                raw_profile = pd.concat([raw_profile, em_fin], axis = 0)
                print('finished day', day)

            # add timestamp and year to raw profile     
            raw_profile['timestamp'] = pd.to_datetime(raw_profile['date'] + ' ' + raw_profile['hour'].astype(str) + ':00:00')
            raw_profile['year'] = raw_profile['timestamp'].dt.year

            # convert raw profile into scaling factors by dividing by mean emission
            temporal_profile = pd.DataFrame()
            for idx, grp in raw_profile.groupby(['component', 'year']):
                grp['scaling_factor'] = grp['emission'] / grp['emission'].mean()
                temporal_profile = pd.concat([temporal_profile, grp[['year', 'component', 'timestamp', 'scaling_factor']]], axis = 0)

            # store temporal profiles
            if store_timeprofiles: 
                store_path = data_paths.INVENTORY_PATH +'/temporal_profiles/'

                # store individual file for each year
                for (year, component), data in temporal_profile.groupby(['year', 'component']):
                    temporal_profile.to_csv(store_path + f'temporal_profile_{component}_{year}.csv', index = False)


        # In[ ]:


        store_path = data_paths.INVENTORY_PATH +'/temporal_profiles/'

        # store individual file for each year
        if store_timeprofiles:
            temporal_profile.to_csv(store_path + f'temporal_profile_{year}.csv', index = False)
    except Exception as e:
        print(e)
        return False
    return True

