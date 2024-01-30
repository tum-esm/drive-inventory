"""This module holds tools to convert line sources to gridded area sources.
"""

__version__ = 0.2
__author__ = 'Daniel Kühbacher'

import geopandas as gpd
import numpy as np

from shapely.geometry import Polygon


class GriddingEngine:
    """This class provides functions to make grids and perform gridding
    """
    def __init__(self, 
                 crs:int, 
                 input_grid:gpd.GeoDataFrame=gpd.GeoDataFrame(),
                 ) -> None:
        """Initialize input grid and CRS

        Args:
            input_grid (gpd.GeoDataFrame, optional): polygon geodataframe that can 
            be used as input grid. Defaults to None.
            crs (int, optional): Coordinate Reference System. Defaults to 4326.
        """

        # define grid from input grid if not none
        self.crs = crs
        self.grid = input_grid
        self.grid = input_grid.to_crs(crs)

        

    def make_grid(self, h_step:float, w_step:float, x_min:float, 
                  y_min:float, x_max:float, y_max:float) -> gpd.GeoDataFrame:
        """Makes polygon grid based on input parameters

        Args:
            h_step (float): horizonal gridding step (e.g. 0.1 degree)
            w_step (float): vertical gridding step (e.g. 0.1 degree)
            x_min (float): x minimum bound of the grid
            y_min (float): y minimum bound of the grid
            x_max (float): x maximum bound of the grid
            y_max (float): y maximum bound of the grid

        Returns:
            gpd.GeoDataFrame: grid of polygons
        """
        
        assert x_min < x_max
        assert y_min < y_max
        assert h_step > 0
        assert w_step > 0
        
        # calculate the number of rows and colums that fit in the 
        # area of interest
        n_rows = int(np.ceil((y_max-y_min) / h_step))
        n_cols = int(np.ceil((x_max-x_min) / w_step))

        # define root cells -> bottom left
        XleftOrigin = x_min
        XrightOrigin = x_min + w_step
        YtopOrigin = y_min
        YbottomOrigin = y_min + h_step

        polygons = []

        for i in range(n_cols):
            Ytop = YtopOrigin
            Ybottom = YbottomOrigin
            for j in range(n_rows):
                polygons.append(Polygon([(XleftOrigin, Ytop), 
                                         (XrightOrigin, Ytop), 
                                         (XrightOrigin, Ybottom), 
                                         (XleftOrigin, Ybottom)])) 
                Ytop = Ytop + h_step
                Ybottom = Ybottom + h_step
            XleftOrigin = XleftOrigin + w_step
            XrightOrigin = XrightOrigin + w_step
            
        self.grid = gpd.GeoDataFrame({'geometry':polygons}, crs=str(self.crs))
        return self.grid


    def overlay_grid(self, 
                     geom_input:gpd.GeoDataFrame,
                     value_columns:[list,str],
                     source_type:str) ->gpd.GeoDataFrame:
        """Overlay emission sources with grid and calculate gridded product

        Args:
            geom_input (gpd.GeoDataFrame): emission geodata to be gridded
            value_columns (list,str]): value column or columns
            source_type (str): emission type: 'area', 'line'

        Returns:
            gpd.GeoDataFrame: gridded emissions
        """
        
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
        elif type(value_columns) == str: 
            data_geo[value_columns] = data_geo[value_columns].astype('float') * data_geo['PROXY']
        else: 
            return None
        
        # reduce geometry to centeroids for exact assignment
        data_geo = data_geo.set_geometry(data_geo.geometry.centroid)
        
        # join geodata with grid cells and sum emissions of the cell
        gridded_aux = gpd.sjoin(self.grid, data_geo, how="right", predicate='contains')
        em_grouped = gridded_aux.groupby('index_left').sum(numeric_only = True)
        
        return_grid = self.grid.copy()
        
        if type(value_columns) == list:
            for col in value_columns:
                return_grid[col] = em_grouped[col]
        elif type(value_columns) == str: 
            return_grid[value_columns] = em_grouped[value_columns]
        else:
            return None
    
        return return_grid.fillna(0)


if __name__ == '__main__':
    """Test the function
    """
    
    gridding_obj = GriddingEngine()
    gridding_obj.make_grid(1000, 1000, 
                           x_min = 675000, x_max = 703000,
                           y_min = 5325800, y_max = 5347800)

    print(gridding_obj.grid.head())

