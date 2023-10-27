# paths to all relevant files and folders in the project

# get absolute path to the traffic inventory folder
import pathlib
abs_path = str(pathlib.Path(__file__).parent.parent.resolve())

#auxiliary_data
CALENDER_FILE = abs_path + "/data/auxiliary/calender_18to23.xlsx"
MUNICH_BOARDERS_FILE = abs_path + "/data/auxiliary/geodata/munich_boarders.gpkg"
MUNICH_BOARDERS_EXTENDED_FILE = abs_path + "/data/auxiliary/geodata/munich_boarders_extended.gpkg" # also includes the motorway around Munich

# visum path´
VISUM_FOLDER_PATH = abs_path + "/data/restricted_input/visum/"