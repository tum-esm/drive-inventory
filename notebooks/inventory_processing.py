# this function was exported to allow multiprocessing.
import numpy as np
import pandas as pd

from traffic_counts import TrafficCounts
from hbefa_hot_emissions import HbefaHotEmissions
from hbefa_cold_emissions import HbefaColdEmissions

def calculate_daily_co2_emissions(date: str, 
                                  visum_dict:dict, 
                                  cycles_obj:TrafficCounts, 
                                  hbefa_obj:HbefaHotEmissions,
                                  multiply_with_length = True
                                  ) -> dict:
    try:
        
        year = int(date[:4]) #convert year to integer
        
        diurnal_cycles = cycles_obj.get_hourly_scaling_factors(date=date)
        vehicle_shares = cycles_obj.get_vehicle_share(date=date).to_dict()
        daily_scaling = cycles_obj.get_daily_scaling_factors(date=date).to_dict()

        em_sum_dict = dict()
        
        # loop over visum model
        for row in visum_dict:

            # get relevant information from the visum model
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
            
            # calculate vehicle counts and apply vehicle share correction factor
            dtv = dict()
            dtv_day = dtv_visum * daily_scaling[scaling_road_type]
            dtv.update({'HGV' : (dtv_day * hgv_share * hgv_corr)})
            dtv.update({'LCV' : (dtv_day * lcv_share * lcv_corr)})
            dtv.update({'PC' : (dtv_day * pc_share * k)})
            dtv.update({'MOT' : (dtv_day * mot_share * k)})
            dtv.update({'BUS' : (dtv_day * bus_share * k)})
            
            # calculate emissions on the respective road link
            em = hbefa_obj.calculate_emissions_daily(dtv_vehicle = dtv,
                                                     diurnal_cycle_vehicle = diurnal_cycles,
                                                     road_type = row['road_type'], 
                                                     hbefa_gradient = row['hbefa_gradient'], 
                                                     hbefa_speed = row['hbefa_speed'],
                                                     hour_capacity = row['hour_capacity'], 
                                                     year = year)
            
            if multiply_with_length:
                for key, value in em.items():
                    em[key] = value * row['geometry'].length/1000
                em_sum_dict.update({row['index']:em})
            else: 
                em_sum_dict.update({row['index']:em})
        
        print('Finished '+ date)
        return em_sum_dict
    
    except Exception as e:
        print('Cannot process '+ date )
        print('Error: ' + str(e))
        return 0
    
    
def calculate_coldstart_emissions(date, 
                                  counts, 
                                  activity, 
                                  visum_zones, 
                                  temperature,
                                  cs_obj):
    
    print('Process ' +date)
    
    datestring = date
    year = int(date[:4])
    daily_emissions = list()
    
    # calculate hourly starts
    diurnal_cycle_PC = counts.get_hourly_scaling_factors(date = datestring).loc['PC']
    daily_starts = visum_zones['qv_pkw'] * activity[date]
    hourly_starts = np.vstack(daily_starts.to_numpy()) * diurnal_cycle_PC.to_numpy()
    
    # temperature_profile
    temperture_profile = temperature.loc[datestring].to_numpy()
    
    #daily_emissions = list()
    for row in hourly_starts:
        em = cs_obj.calculate_emission_daily(hourly_temperature=temperture_profile, 
                                         hourly_starts = row, 
                                         vehicle_class='pass. car', 
                                         year = year)
        
        daily_emissions.append(em)
    
    return pd.concat(daily_emissions, axis=1).sum(axis =1)