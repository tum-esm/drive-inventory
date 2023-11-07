"""Module to import a predefined calendar for different years.
The path to the calender excel file should be defined in data_paths.py (utils)
"""

__version__ = 1.1
__author__ = 'Daniel Kühbacher'

import pandas as pd

import data_paths


def fetch_calendar(year:int, 
                   date_is_index:bool=False) -> pd.DataFrame:
    """Loads calendar *.xlsx shee from path defined in 
    data_paths.json and returns it as dataframe.

    Args:
        year (int): Year of the requested calendar
        date_is_index (bool, optional): sets date as index if True. 
        Defaults to False.

    Returns:
        pd.DataFrame: Dataframe holing the calendar of a defined year.
    """
    
    # load data path to calendar file
    calendar_path = data_paths.CALENDER_FILE
    
    try: 
        df = pd.read_excel(calendar_path, sheet_name=str(year))
        df['date'] = pd.to_datetime(df['date'])
        
        if date_is_index:
            df = df.set_index('date')
            
        return df
    except Exception as e:
        print('Could not load calendar. Check path and year.')
        print(e)


def find_day_type(day:pd.Series) -> int:
    cal_day_type = day['day_type']
    cal_weekday = day['day_of_week']
    
    # Normweekday -> Tuesday to Thursday (used in traffic planning)
    if cal_day_type==1 and (cal_weekday>=1 and cal_weekday<=3):
        return 0
    # Weekday -> Monday to Friday
    if cal_day_type==1: 
        return 1 
    # Weekday during vacation / gap day
    if cal_day_type==4 or cal_day_type==5: 
        return 2
    # Saturday
    if cal_day_type==2 and cal_weekday==5: 
        return 3
    # Sunday/ Holiday -> shops are closed in Germany
    if cal_day_type==3 or cal_weekday==6:
        return 4
    else: 
        print('Error', cal_day_type, cal_weekday)