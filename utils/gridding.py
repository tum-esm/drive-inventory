"""This module holds tools to convert line sources to gridded area sources.

- prepare emission grid
- 


"""

__version__ = 0.1
__author__ = 'Daniel Kühbacher'

import geopandas as gpd
import numpy as np

from shapely.geometry import Polygon



class GriddingEngine: 
    def __init__(self, input_grid:gpd.GeoDataFrame=None) -> None:
        if input_grid is not None:
            assert input_grid.geom_type == 'Polygon'
        
        self.grid = input_grid
        self.crs = 25832
    
    def make_grid(self, h_step:float, w_step:float, x_min:float, 
                  y_min:float, x_max:float, y_max:float) -> None:
        
        assert x_min<x_max
        assert y_min<y_max
        assert h_step>0
        assert w_step>0
        
        # calculate the number of rows and colums that fit in the 
        # area of interest
        n_rows = int(np.ceil((y_max-y_min) / h_step))
        n_cols = int(np.ceil((x_max-x_min) / w_step))

        # define root cells -> top left
        XleftOrigin = x_min
        XrightOrigin = x_max + w_step
        YtopOrigin = y_max
        YbottomOrigin = y_max - h_step

        polygons = []

        for i in range(n_cols):
            Ytop = YtopOrigin
            Ybottom = YbottomOrigin
            for j in range(n_rows):
                polygons.append(Polygon([(XleftOrigin, Ytop), 
                                         (XrightOrigin, Ytop), 
                                         (XrightOrigin, Ybottom), 
                                         (XleftOrigin, Ybottom)])) 
                Ytop = Ytop - h_step
                Ybottom = Ybottom - h_step
            XleftOrigin = XleftOrigin + w_step
            XrightOrigin = XrightOrigin + w_step
            
            self.grid = gpd.GeoDataFrame({'geometry':polygons}, crs=str(self.crs))
            

if __name__ == '__main__': 
    
    xmin = 675000
    xmax = 703000
    ymin = 5325800
    ymax = 5347800
    
    gridding_obj = GriddingEngine()
    gridding_obj.make_grid(1000,1000,x_min = 675000,x_max = 703000,y_min = 5325800, y_max = 5347800)

    print(gridding_obj.grid.head())

