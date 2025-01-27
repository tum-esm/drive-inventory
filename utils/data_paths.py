# Project file and folder paths

# get absolute path to the project folder
import pathlib
abs_path = str(pathlib.Path(__file__).parent.parent.resolve())

#INPUT DATA
#auxiliary_data
CALENDER_FILE = abs_path + "/data/auxiliary/calender_18to23.xlsx"
MUNICH_BOARDERS_FILE = abs_path + "/data/geodata/munich_boarders.gpkg"
# extended boarders including the surrounding motorway
MUNICH_BOARDERS_EXTENDED_FILE = abs_path + "/data/geodata/munich_boarders_extended.gpkg"
TNO_100M_GRID  = abs_path + "/data/geodata/TNO_100m_grid.gpkg"
TNO_1km_GRID = abs_path + "/data/geodata/TNO_1km_grid.gpkg"

# traffic model
VISUM_FOLDER_PATH = abs_path + "/data/restricted_input/visum/"

# traffic counting data
COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/"
MST_COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/lhm/"
BAST_COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/bast/"
COMBINED_COUNTING_DATA = COUNTING_PATH + "counting_data_combined.parquet"


# HBEFA emission factors
EF_PATH = abs_path + "/data/restricted_input/hbefa/"
EF_AGG = abs_path + "/data/restricted_input/hbefa/EFA_HOT_aggregated_hbefa.txt"
EF_COLD = abs_path + "/data/restricted_input/hbefa/EFA_ColdStart_hbefa.txt"

# OUTPUT DATA
# inventory output folder
INVENTORY_PATH = abs_path + "/data/inventory/"
# timeprofile output folder
TIMEPROFILE_PATH = abs_path + "/data/inventory/timeprofile/"