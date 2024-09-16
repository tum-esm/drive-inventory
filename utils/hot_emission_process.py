"""This module implements a process to calculate daily emissions for a given date
by accessing the emission calculation moduls as well as the traffic count. 
The process can be run in parallel to speed up the calculation process.
"""
    
__version__ = 0.1
__author__ = "Daniel Kühbacher"

import numpy as np
from typing import Literal
from multiprocessing import Queue

from traffic_counts import TrafficCounts
from hbefa_hot_emissions import HbefaHotEmissions


def process_daily_emissions(date: str,
                            mode:Literal['aggregated', 'los_specific'],
                            visum_dict:dict,
                            cycles_obj:TrafficCounts,
                            hbefa_obj:HbefaHotEmissions,
                            result_queue: Queue,
                            error_queue: Queue,
                            ) -> bool:
    """Function to calculate daily emissions for a given date. 
    This implements the HbefaHotEmissions object and can be run as parallell processes.

    Args:
        date (str): day to be calculated
        visum_dict (dict): traffic model as dict for faster looping
        cycles_obj (TrafficCounts): object to access traffic cycles
        hbefa_obj (HbefaHotEmissions): object to access emission factors
        result_queue (Queue): results
        error_queue (Queue): errors
        multiply_with_length (bool, optional): if True, mutliplies with road length 
        to acquire total Emissions. Defaults to True.

    Returns:
        bool: true if process finished without error, false if not.
    """
    try:
        
        year = int(date[:4]) #convert year to integer
        
        # get scaling factors for the day
        diurnal_cycles = cycles_obj.get_hourly_scaling_factors(date=date)
        vehicle_shares = cycles_obj.get_vehicle_share(date=date).to_dict()
        daily_scaling = cycles_obj.get_daily_scaling_factors(date=date).to_dict()

        emission_sum_dict = dict() # initialize result dict
        
        # loop over all rows in the visum model
        for row in visum_dict:
            
            # relevant information from the visum model
            dtv_visum = row['dtv_SUM']
            hgv_corr = row['hgv_corr']
            lcv_corr = row['lcv_corr']
            scaling_road_type = row['scaling_road_type']
            
            # get vehicle shares from counting data
            hgv_share = vehicle_shares['HGV'][scaling_road_type]
            lcv_share = vehicle_shares['LCV'][scaling_road_type]
            pc_share = vehicle_shares['PC'][scaling_road_type]
            mot_share = vehicle_shares['MOT'][scaling_road_type]
            bus_share = vehicle_shares['BUS'][scaling_road_type]
            
            # calculate vehicle share correction factor
            k = (1- (hgv_corr * hgv_share)- (lcv_corr * lcv_share)) / \
                (1 - hgv_share - lcv_share)
            
            # calculate vehicle counts and apply vehicle share correction factor
            dtv = dict()
            dtv_day = dtv_visum * daily_scaling[scaling_road_type]
            dtv.update({'HGV' : (dtv_day * hgv_share * hgv_corr)})
            dtv.update({'LCV' : (dtv_day * lcv_share * lcv_corr)})
            dtv.update({'PC' : (dtv_day * pc_share * k)})
            dtv.update({'MOT' : (dtv_day * mot_share * k)})
            dtv.update({'BUS' : (dtv_day * bus_share * k)})
            
            # calculate emissions on the respective road link depending on selected mode
            if mode == 'aggregated':
                em = hbefa_obj.calculate_emissions_daily(dtv_vehicle = dtv,
                                                mode = 'aggregated',
                                                diurnal_cycle_vehicle = diurnal_cycles,
                                                road_type = row['road_type'], 
                                                hbefa_gradient = row['hbefa_gradient'],
                                                hbefa_speed = row['hbefa_speed'],
                                                hour_capacity = row['hour_capacity'],
                                                year = year)
            if mode == 'los_specific':
                em = hbefa_obj.calculate_emissions_daily(dtv_vehicle = dtv,
                                                mode = 'los_specific',
                                                diurnal_cycle_vehicle = diurnal_cycles,
                                                road_type = row['road_type'],
                                                hbefa_gradient = row['hbefa_gradient'],
                                                hbefa_speed = row['hbefa_speed'],
                                                hour_capacity = row['hour_capacity'],
                                                year = year)
            
            emission_sum_dict.update({row['index']:em}) # add emmissions to emission dict

            
        print('Finished calculating '+ date)
        
        # add emission results to queue
        if result_queue.empty():
            result_queue.put(emission_sum_dict)
        else: # append to existing results if queue is not empty
            old_result = result_queue.get(timeout=60)
            for road_index, emissions in old_result.items():
                for component, value in emissions.items():
                    add_emissions = emission_sum_dict[road_index][component]
                    old_result[road_index][component] += add_emissions
            result_queue.put(old_result)
        return True
    
    except Exception as e:
        error_queue.put({date:e})
        print('Cannot process '+ date )
        return False


def process_hourly_emissions(date: str,
                            visum_dict: dict,
                            cycles_obj: TrafficCounts,
                            hbefa_obj: HbefaHotEmissions) -> dict:
    """Calculates hourly emissions for a given date.
    Should only be used for testing or small visum extents, otherwise it is too slow.

    Args:
        date (str): Date to be calculated
        visum_dict (dict): Visum model as dict for faster looping
        cycles_obj (TrafficCounts): Traffic counting object
        hbefa_obj (HbefaHotEmissions): Hbefa hot emissions object

    Returns:
        Dict: Hot emissions for given date at hourly resolution
    """
    try: 
        year = int(date[:4]) #convert year to integer

        # get scaling factors for the day
        diurnal_cycles = cycles_obj.get_hourly_scaling_factors(date=date)
        vehicle_shares = cycles_obj.get_vehicle_share(date=date).to_dict()
        daily_scaling = cycles_obj.get_daily_scaling_factors(date=date).to_dict()

        emission_sum_dict = dict() # initialize result dict
        
        # loop over visum model
        for row in visum_dict:
            
            # relevant information from the visum model
            dtv_visum = row['dtv_SUM']
            hgv_corr = row['hgv_corr']
            lcv_corr = row['lcv_corr']
            scaling_road_type = row['scaling_road_type']
            
            # get vehicle shares from counting data
            hgv_share = vehicle_shares['HGV'][scaling_road_type]
            lcv_share = vehicle_shares['LCV'][scaling_road_type]
            pc_share = vehicle_shares['PC'][scaling_road_type]
            mot_share = vehicle_shares['MOT'][scaling_road_type]
            bus_share = vehicle_shares['BUS'][scaling_road_type]
            
            # calculate vehicle share correction factor
            k = (1- (hgv_corr * hgv_share)- (lcv_corr * lcv_share)) / \
                (1 - hgv_share - lcv_share)
            
            # calculate vehicle counts and apply vehicle share correction factor
            dtv = dict()
            dtv_day = dtv_visum * daily_scaling[scaling_road_type]
            dtv.update({'HGV' : (dtv_day * hgv_share * hgv_corr)})
            dtv.update({'LCV' : (dtv_day * lcv_share * lcv_corr)})
            dtv.update({'PC' : (dtv_day * pc_share * k)})
            dtv.update({'MOT' : (dtv_day * mot_share * k)})
            dtv.update({'BUS' : (dtv_day * bus_share * k)})
            
            # calculate emissions on the respective road link
            em = hbefa_obj.calculate_emissions_hourly(dtv_vehicle = dtv,
                                                diurnal_cycle_vehicle = diurnal_cycles,
                                                road_type = row['road_type'], 
                                                hbefa_gradient = row['hbefa_gradient'], 
                                                hbefa_speed = row['hbefa_speed'],
                                                hour_capacity = row['hour_capacity'], 
                                                year = year)
            
            emission_sum_dict.update({row['index']:em}) # add emmissions to dict
        return emission_sum_dict
    except Exception:
        return np.nan
    