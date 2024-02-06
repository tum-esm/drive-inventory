# this function was exported to allow multiprocessing.
from multiprocessing import Queue

from traffic_counts import TrafficCounts
from hbefa_hot_emissions import HbefaHotEmissions

def process_daily_emissions(date: str,
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

        em_sum_dict = dict() # initialize result dict
        
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
            
            em_sum_dict.update({row['index']:em}) # add emmissions to emission dict

            
        print('Finished calculating '+ date)
        # add emissions to queued result 
        if result_queue.empty():
            result_queue.put(em_sum_dict)
        else:
            old_result = result_queue.get_nowait()
            for road_index, emissions in old_result.items():
                for component, value in emissions.items():
                    add_emissions = em_sum_dict[road_index][component]
                    old_result[road_index][component] += add_emissions
            result_queue.put(old_result)
        return True
    
    except Exception as e:
        error_queue.put({date:e})
        print('Cannot process '+ date )
        return False
    