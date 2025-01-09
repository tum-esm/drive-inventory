
import numpy as np
from traffic_counts import TrafficCounts
from hbefa_hot_emissions import HbefaHotEmissions

from itertools import chain

def calculate_VKT(date: str,
                  visum_dict:dict,
                  cycles_obj:TrafficCounts,
                  hbefa_obj:HbefaHotEmissions,
                  ) -> bool:
    """Function to calculate daily emissions for a given date. 
    This implements the HbefaHotEmissions object and can be run as parallell processes.

    Args:
        date (str): day to be calculated
        visum_dict (dict): traffic model as dict for faster looping
        cycles_obj (TrafficCounts): object to access traffic cycles
        hbefa_obj (HbefaHotEmissions): object to access emission factors
    Returns:
        bool: true if process finished without error, false if not.
    """
    # get scaling factors for the day
    diurnal_cycles = cycles_obj.get_hourly_scaling_factors(date= date)
    vehicle_shares = cycles_obj.get_vehicle_share(date= date).to_dict()
    daily_scaling = cycles_obj.get_daily_scaling_factors(date= date).to_dict()
    
    # initialize result variables
    result = list()
    final_result = {'Freeflow': np.array(5, float),
                    'Heavy': np.array(5, float),
                    'Satur.': np.array(5, float),
                    'St+Go': np.array(5, float),
                    'St+Go2': np.array(5, float)}
    
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
        k = (1- (hgv_corr * hgv_share)- (lcv_corr * lcv_share)) / (1 - hgv_share - lcv_share)
        
        # calculate vehicle counts
        dtv = dict()
        dtv_day = dtv_visum * daily_scaling[scaling_road_type] # daily traffic volume
        dtv.update({'HGV' : (dtv_day * hgv_share * hgv_corr)})
        dtv.update({'LCV' : (dtv_day * lcv_share * lcv_corr)})
        dtv.update({'PC' : (dtv_day * pc_share * k)})
        dtv.update({'MOT' : (dtv_day * mot_share * k)})
        dtv.update({'BUS' : (dtv_day * bus_share * k)})
        
        # disaggregate daily traffic to hourly traffic for each vehicle class
        dtv_array = np.array([dtv[v] for v in diurnal_cycles.index])
        htv = (np.transpose(diurnal_cycles.to_numpy()) * dtv_array)
        
        # convert hourly traffic volume to personal car equivalents
        htv_car_units = np.array([HbefaHotEmissions.car_unit_factors[v]\
            for v in diurnal_cycles.index])
        htv_car_units = (htv * htv_car_units).sum(axis=1)
        
        # list of 24 service classes for each hour of the day
        los_class = [hbefa_obj.calc_los_class(htv_car_unit = x,
                                                hour_capacity = row['hour_capacity'],
                                                road_type = row['road_type'],
                                                hbefa_speed = row['hbefa_speed'])
                        for x in htv_car_units]
        los =  [x.split('/')[-1] for x in los_class]

        # now calculate vehicle kilometers
        veh_kilometers  = htv * row['road_lenght'] *1e-3 # in km

        # zip los class and vehicle kilometers and append to result list
        result.append(list(zip(los, veh_kilometers)))
    
    # sum up the results
    for e in list(chain(*result)):
        final_result[e[0]] = final_result[e[0]] + e[1]
    
    return final_result, diurnal_cycles.index