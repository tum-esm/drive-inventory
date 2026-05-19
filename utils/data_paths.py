# Project file and folder paths

# get absolute path to the project folder
import pathlib
abs_path = str(pathlib.Path(__file__).parent.parent.resolve())

#INPUT DATA
DATA_PATH = abs_path + "/data/"
#auxiliary_data
BAST_LOCATIONS_FILE = abs_path + "/data/auxiliary/bast_locations_selected.gpkg"
CALENDER_FILE = abs_path + "/data/auxiliary/calender_18to26.xlsx"
MUNICH_BOARDERS_FILE = abs_path + "/data/geodata/munich_boarders.gpkg"

# extended boarders including the surrounding motorway
MUNICH_BOARDERS_EXTENDED_FILE = abs_path + "/data/geodata/munich_boarders_extended.gpkg"

#Spatial grids
TNO_100M_GRID  = abs_path + "/data/geodata/TNO_100m_grid_munich.gpkg"
TNO_1km_GRID = abs_path + "/data/geodata/TNO_1km_grid_munich.gpkg"

# traffic model
VISUM_2019_FOLDER_PATH = abs_path + "/data/restricted_input/traffic_model_2019/"
VISUM_2025_FOLDER_PATH = abs_path + "/data/restricted_input/traffic_model_2025/"

# traffic counting data
COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/"
MST_COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/lhm/"
BAST_COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/bast/"
COMBINED_COUNTING_DATA = COUNTING_PATH + "counting_data_combined.parquet"

# HBEFA emission factors
EF_PATH = abs_path + "/data/restricted_input/hbefa/"

# OUTPUT DATA
# inventory output folder
INVENTORY_PATH = abs_path + "/data/inventory/"
# timeprofile output folder
TIMEPROFILE_PATH = abs_path + "/data/inventory/timeprofile/"

# path to env file
ENV_PATH = abs_path + "/utils/.env"