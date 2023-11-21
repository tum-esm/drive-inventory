"""Utils to import and prepare traffic counting datasets.
"""

import data_paths
import pandas as pd
import geopandas as gpd
from excel_calendar import Calendar
    
class TrafficCounts:
    """
    """ 
    
    def __init__(self): 
        # define file paths
        mst_file_path = data_paths.MST_COUNTING_PATH + 'preprocessed_lhm_counting_data.parquet'
        bast_file_path = data_paths.BAST_COUNTING_PATH + 'preprocessed_bast_counting_data.parquet'
        visum_file_path = data_paths.VISUM_FOLDER_PATH + 'visum_links.gpkg'

        self._counting_data = pd.concat([pd.read_parquet(mst_file_path), # import counting data
                                pd.read_parquet(bast_file_path)], axis=0)
        self._visum = gpd.read_file(visum_file_path) #import visum_links data
        self._cal_obj = Calendar() #import calendar
        
        self.volume = self._clean_volume_data()
        #self.speed  = self._clean_speed_data()
    
    
    def _clean_volume_data(self) -> pd.DataFrame():
        """_summary_

        Returns:
            _type_: _description_
        """
        # aggregate and reduce to volume dataset
        volume  = self._counting_data.groupby(['metric','road_link_id', 
                                    'vehicle_class','date']).sum(numeric_only = True).loc['volume']
        volume = volume.drop(['detector_id'], axis =1)
        volume = volume.reset_index()
        
        # add road type information
        road_types = self._visum.set_index('road_link_id')['road_type'].to_dict()
        volume.insert(4,'road_type' , volume['road_link_id'].map(road_types))

        # add day type information
        dates = volume['date'].unique()
        day_types = {date:self._cal_obj.get_day_type(date) for date in dates}
        volume.insert(5, 'day_type', volume['date'].map(day_types))

        # drop rows with NaN values
        volume = volume.dropna()
        
        # delete inconssitent counting rows
        e = 0.05
        volume = volume[volume.iloc[:,-25:].sum(axis=1).between(
            volume['daily_value']*(1-e), volume['daily_value']*(1+e))]
        
        # drop rows with daily_volume <10
        volume = volume[volume['daily_value']>10]
        
        return volume
            

    def get_volume(self):
        return self.volume


    def get_speed_counts(self): 
        pass
    

if __name__ == "__main__":
    
    counts = TrafficCounts()