"""tbd
"""

import data_paths
import pandas as pd
import geopandas as gpd

    
class TrafficCounts:
    """ Reads combined counting data calculates and provides an interface to the traffic cycles.
    """ 
    
    def __init__(self):
        """__summary__
        """
        file_path = data_paths.COUNTING_PATH + 'counting_data_combined.parquet'
        self.df = pd.read_parquet(file_path)
    
    def get_daily_cycle(self, day_type, road_type):
        pass
    
    def _calc_activity(self):
        pass
        
        
if __name__ == "__main__":
    count = TrafficCounts()
    

    