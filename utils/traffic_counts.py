"""tbd
"""
__version__ = 2.0
__author__ = 'Ali Ahmad Khan'

import data_paths
import pandas as pd
import geopandas as gpd
from datetime import datetime

class TrafficCounts:
    """ Reads combined counting data calculates and provides an interface to the traffic cycles.
    """ 
    
    def __init__(self):
        """__summary__
        """
        file_path = data_paths.COUNTING_PATH + 'counting_data_combined.parquet'
        self.counting_df = pd.read_parquet(file_path)
        self.counting_df['date'] = pd.to_datetime(self.counting_df['date'])

        self.visum_df = gpd.read_file(data_paths.VISUM_FOLDER_PATH+'visum_links.gpkg')
    
    def get_daily_cycle(self, day_type, road_type):
        pass
    
    def _calc_activity(self):
        pass

    def get_day_type(self, date:str):

        # Finds the specific day type the given date correlates to
        day_type = self.counting_df[(self.counting_df.date == date)]['day_type'].iloc[0]
        
        return day_type

    def get_dtv(self):
        
        road_type_mean = self.visum_df.groupby('road_type').dtv_KFZ.mean()
        dtv = road_type_mean.mean()
        
        return round(dtv, 2)
    
    def get_daily_scaling_factor(self, road_type: str, date: str):

        # Convert the date string to a datetime object
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        
        # Calculate the daily sum of traffic for the given week number and day type
        daily_sum = self.counting_df[(self.counting_df.road_type == road_type) & 
                                     (self.counting_df.day_type == self.get_day_type(date)) & 
                                     (self.counting_df['date'].dt.isocalendar().week == date_obj.isocalendar().week) & 
                                     (self.counting_df.vehicle_class == 'SUM')]['daily_value']
        
        # Calculate the daily sum mean of traffic for the given week number and day type
        daily_mean = daily_sum.mean()
        print(daily_mean)
        
        # Calculate the daily sum of traffic for norm weekday in 2019
        daily_sum_2019 = self.counting_df[(self.counting_df['date'].between('2019-01-01','2019-12-31')) & 
                                          (self.counting_df.road_type == road_type) & (self.counting_df.day_type == 0) & 
                                          (self.counting_df.vehicle_class == 'SUM')]['daily_value']
        
        # Calculate the daily sum mean of traffic for norm weekday in 2019
        daily_mean_2019 = daily_sum_2019.mean()
        print(daily_mean_2019)

        return round(daily_mean/daily_mean_2019, 2)

    def get_hourly_scaling_factor(self, road_type: str, day_type: int, hour: int):

        # Calculate the specific hourly sum mean on a road link on a given day type
        hourly_sum = self.counting_df[(self.counting_df.road_type == road_type) & 
                                      (self.counting_df.day_type == day_type) & 
                                      (self.counting_df.vehicle_class == 'SUM')][str(hour)].mean()
        
        # Calculate the daily sum mean on a road link on a given day type
        daily_sum = self.counting_df[(self.counting_df.road_type == road_type) & 
                                     (self.counting_df.day_type == day_type) & 
                                     (self.counting_df.vehicle_class == 'SUM')]['daily_value'].mean()
        

        return round(hourly_sum/daily_sum, 2)


    def get_vehicle_share(self, road_type, day_type, vehicle_class):

        # Calculate the specific vehicle sum mean on a road link on a given day type
        vehicle_sum = self.counting_df[(self.counting_df.road_type == road_type) & 
                                       (self.counting_df.day_type == day_type) & 
                                       (self.counting_df.vehicle_class == vehicle_class)]['daily_value'].mean()
        

        # Calculate all vehicles sum mean on a road link on a given day type
        all_vehicle_sum = self.counting_df[(self.counting_df.road_type == road_type) & 
                                           (self.counting_df.day_type == day_type) & 
                                           (self.counting_df.vehicle_class == 'SUM')]['daily_value'].mean()

        return round(vehicle_sum/all_vehicle_sum, 2)        
        
if __name__ == "__main__":
    count = TrafficCounts()
    total = 0
    print(count.dtv("2019-01-02"))

    