"""Module to import and access a predefined calendar file for different years.
The path to the calender excel file should be defined in data_paths.py (utils)
"""

__version__ = 2.2
__author__ = 'Daniel Kühbacher'

import pandas as pd

import data_paths
from dateutil.parser import parse


class Calendar:
    
    def __init__(self,
                 years:list = [2018, 2019, 2020, 2021, 2022, 2023]) -> None:
        """Initializes the calender object and loads from calender file

        Args:
            years (list, optional): years to parse from calendar xlsx file.
            Defaults to [2018, 2019, 2020, 2021, 2022, 2023].
        """
        self.cal = self._fetch_calendar(years[0])
        for year in years[1:]:
            self.cal = pd.concat([self.cal, self._fetch_calendar(year)], axis=0)
        self.cal['date'] = pd.to_datetime(self.cal['date'], format='%Y-%m-%d')


    def get_calendar(self) -> pd.DataFrame:
        return self.cal


    def _fetch_calendar(self, year:int) -> pd.DataFrame:
        """Loads calendar *.xlsx sheet from path defined in 
        data_paths.py and returns it as dataframe.

        Args:
            year (int): Year of the requested calendar
            date_is_index (bool, optional): sets date as index if True. 
            Defaults to False.

        Returns:
            pd.DataFrame: Dataframe holing the calendar of a defined year.
        """
        try: 
            df = pd.read_excel(data_paths.CALENDER_FILE, sheet_name=str(year))
            df['date'] = pd.to_datetime(df['date'])
            return df
        except Exception as e:
            print('Could not load calendar. Check path and year.')
            print(e)


    def get_weekday(self, date_string: str) -> int:
        """Returns weekday as integer (0=Monday, 1=Tuesday, ..., 6=Sunday) form 
        calendar file

        Args:
            date_string (str): datetime object or string to be parsed

        Returns:
            int: weekday as integer
        """
        if isinstance(date_string, str):
            try:
                dt = parse(date_string)
            except Exception: 
                print(f'Could not parse datestring {date_string}.')
                return None
        else: 
            dt = date_string
        
        cal_indexed = self.cal.set_index('date')
        return cal_indexed.loc[dt]['day_of_week']


    def get_day_type(self, date_string:str) -> int:
        """returns day type (weekday, weekday during vacation, Saturday,
        Sunday, holiday) from calendar file

        Args:
            date_string (str): datetime object or string to be parsed

        Returns:
            int: day type as integer
        """
        if isinstance(date_string, str):
            try:
                dt = parse(date_string)
            except Exception: 
                print(f'Could not parse datestring {date_string}.')
                return None
        else: 
            dt = date_string
        
        cal_indexed = self.cal.set_index('date')
        return cal_indexed.loc[dt]['day_type']


    def get_day_type_combined(self, date_string) -> int:
        """Returns day types that are based on the weekday and specific 
        day types. These day types are not unique! Normweekday is a subset of weekday.
        0 -> Normweekday (Tuesday to Thursday; relevant in traffic engineering)
        1 -> Weekday
        2 -> Weekday during vacation
        3 -> Saturday
        4 -> Sunday/Holiday (Shops are closed on these days in Germany)

        Args:
            date_string (str): date to be parsed

        Returns:
            int: enumerated day type
        """
        if isinstance(date_string, str):
            try:
                dt = parse(date_string)
            except Exception: 
                print(f'Could not parse datestring {date_string}.')
                return None
        else: 
            dt = date_string
                  
        cal_indexed = self.cal.set_index('date')
        cal_weekday = cal_indexed.loc[dt]['day_of_week']
        cal_day_type = cal_indexed.loc[dt]['day_type']
        
        # Normweekday -> Tuesday to Thursday (used in traffic planning)
        if cal_day_type==1 and (cal_weekday>=1 and cal_weekday<=3):
            return 0
        # Weekday -> Monday to Friday
        if cal_day_type==1:
            return 1
        # Weekday during vacation / gap da
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


if __name__ == "__main__":
    """Testing
    """
    cal = Calendar()
    date_min = cal.get_calendar()["date"].min()
    date_max = cal.get_calendar()["date"].max()
    print(f'Loaded calender from {date_min} until {date_max}')
    print(cal.get_day_type('2022 June 15'))
