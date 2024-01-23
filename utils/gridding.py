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
    def __init__(self, input_grid:gpd.GeoDataFrame = None):
        self.crs = 25832
        # define grid from input grid if not none   
        self.grid = input_grid
        

    def make_grid(self, h_step:float, w_step:float, x_min:float, 
                  y_min:float, x_max:float, y_max:float) -> gpd.GeoDataFrame:
        
        assert x_min < x_max
        assert y_min < y_max
        assert h_step > 0
        assert w_step > 0
        
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


    def overlay_grid(self, geom_input, value_columns, source_type): 
        
        #Make overlay of data (road lengths) with outgrid (output grid)
        data_geo = gpd.overlay(geom_input,
                               self.grid,
                               how = 'intersection',
                               keep_geom_type=True) 

        #Calculate total (PROXY) for each segment cut off by the output grid
        if source_type == 'area':
            data_geo['PROXY'] = data_geo.geometry.area
        elif source_type == 'line': 
            data_geo['PROXY'] = data_geo.geometry.length
        else:
            print(f'Ivalid source type {source_type}. Use `area` or `line` instead.')
            return None
        
        if type(value_columns) == list:
            for col in value_columns: 
                data_geo[col] = data_geo[col].astype('float') * data_geo['PROXY']
        else: 
            pass

        data_geo = data_geo.set_geometry(data_geo.geometry.centroid)
        
        gridded_aux = gpd.sjoin(self.grid, data_geo, how="right", predicate='contains')
        self.grid = gridded_aux.groupby('index_left').sum(numeric_only = True)
        self.grid = self.grid.fillna(0)
    
        return self.grid  

if __name__ == '__main__': 
    
    xmin = 675000
    xmax = 703000
    ymin = 5325800
    ymax = 5347800
    
    gridding_obj = GriddingEngine()
    gridding_obj.make_grid(1000,1000,x_min = 675000,x_max = 703000,y_min = 5325800, y_max = 5347800)

    print(gridding_obj.grid.head())

