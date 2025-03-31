import requests

import pandas as pd
import numpy as np

class meteo_data():
    """_summary_
    """
    def init():
        pass
    
    def _z_score(self, series:pd.Series) -> pd.Series:
        """Calculates z score of each value in given series

        Args:
            series (pd.Series): Series of values where the 
            z_score should be calculated

        Returns:
            pd.Series: Series with z scores.
        """
        m = series.mean()
        s = series.std()
        return np.abs((series-m)/s)
    
    def get_meteo_data(self,
                    parameters: list,
                    station_id: str,
                    start_time : str,
                    end_time: str
                    ) -> pd.DataFrame():
        """Acceesses the LMU meteo api and returns data as dataframe

        Args:
            parameters (list): meteo parameters to download
            station_id (str): ID to select Garching or city station
            start_time (str): start time of retrieval
            end_time (str): end time of retrieval

        Returns:
            (pd.Dataframe): Dataframe with cleaned meteo data
        """
        
        # assemple request url
        try:
            par_string = '+'.join(parameters)
            r = requests.get(f'https://www.meteo.physik.uni-muenchen.de/request-beta/data/'\
                + f'var={par_string}'\
                + f'&station={station_id}'\
                + f'&start={start_time}&end={end_time}')
            
            if r.status_code == 200:
                try: 
                    lmu_data = r.json()
                    lmu_weather = pd.DataFrame(columns=parameters)
                    lmu_weather['time'] = pd.to_datetime(pd.DataFrame(lmu_data["time"])[0], unit='s')
                    for par in parameters:
                        # convert to dataframe
                        lmu_weather[par] = pd.DataFrame(lmu_data[station_id][par])
                        lmu_weather[par] = lmu_weather[par].loc[self._z_score(lmu_weather[par])<3]
                    lmu_weather = lmu_weather.dropna()
                    lmu_weather.set_index('time', inplace=True)
                    lmu_weather.sort_index(inplace=True)
                    return lmu_weather
                except Exception as e:
                    print('Request resulted in an error: ')
                    print(r.json())
                    return None
        except Exception as e:
            print('Request resutlted in an error: '+str(e))
            print(r.json())
            return None