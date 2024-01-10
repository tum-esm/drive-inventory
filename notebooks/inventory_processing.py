def calculate_daily_co2_emissions(date, 
                                  visum_dict, 
                                  cycles, 
                                  hbefa):
    try:
        diurnal_cycles = cycles.get_hourly_scaling_factors(date=date)
        vehicle_shares = cycles.get_vehicle_share(date=date).to_dict()
        daily_scaling = cycles.get_daily_scaling_factors(date=date).to_dict()

        em_sum_dict = dict()

        for row in visum_dict:

            # get relevant information from the visum model
            #road_link_id = row['road_link_id']
            dtv_visum = row['dtv_SUM']
            road_type = row['road_type']
            hour_capacity = row['hour_capacity']
            visum_speed = row['speed']
            visum_slope = row['SLOPE']
            hgv_corr = row['hgv_corr']
            lcv_corr = row['lcv_corr']
            
            # get vehicle shares from counting data
            hgv_share = vehicle_shares['HGV'][road_type]
            lcv_share = vehicle_shares['LCV'][road_type]
            pc_share = vehicle_shares['PC'][road_type]
            mot_share = vehicle_shares['MOT'][road_type]
            bus_share = vehicle_shares['BUS'][road_type]
            
            # calculate vehicle share correction factor
            k = (1- (hgv_corr * hgv_share)- (lcv_corr * lcv_share)) / (1 - hgv_share - lcv_share)
            
            # calculate vehicle counts and apply correction factor
            dtv = dict()
            dtv_day = dtv_visum * daily_scaling[road_type]
            dtv.update({'HGV' : (dtv_day * hgv_share * hgv_corr)})
            dtv.update({'LCV' : (dtv_day * lcv_share * lcv_corr)})
            dtv.update({'PC' : (dtv_day * pc_share * k)})
            dtv.update({'MOT' : (dtv_day * mot_share * k)})
            dtv.update({'BUS' : (dtv_day * bus_share * k)})
            
            # calculate emissions on the respective road link    
            em = hbefa.calculate_emissions_daily(dtv, diurnal_cycles, road_type,
                                                visum_speed, visum_slope, hour_capacity, 2019)
            
            
            for key, value in em.items(): 
                em[key] = value * row['geometry'].length/1000
            em_sum_dict.update({row['index']:em})
        
        print('Finished '+ date)
        return em_sum_dict
    
    except Exception as e:
        print('Cannot process '+ date )
        print('Error: ' + str(e))
        return 0