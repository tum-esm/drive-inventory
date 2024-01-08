# paths to all relevant files and folders in the project

# get absolute path to the traffic inventory folder
import pathlib
abs_path = str(pathlib.Path(__file__).parent.parent.resolve())

#auxiliary_data
CALENDER_FILE = abs_path + "/data/auxiliary/calender_18to23.xlsx"
MUNICH_BOARDERS_FILE = abs_path + "/data/geodata/munich_boarders.gpkg"
MUNICH_BOARDERS_EXTENDED_FILE = abs_path + "/data/geodata/munich_boarders_extended.gpkg" # also includes the motorway around Munich

# visum path
VISUM_FOLDER_PATH = abs_path + "/data/restricted_input/visum/"

# counting data
COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/"
MST_COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/lhm/"
BAST_COUNTING_PATH = abs_path + "/data/restricted_input/counting_data/bast/"

#emission factors
EF_BUS = abs_path + "/data/restricted_input/hbefa/EFA_HOT_Vehcat_Coach.XLS"
EF_PC = abs_path + "/data/restricted_input/hbefa/EFA_HOT_Vehcat_PC.XLS"
EF_LCV = abs_path + "/data/restricted_input/hbefa/EFA_HOT_Vehcat_LCV.XLS"
EF_HGV = abs_path + "/data/restricted_input/hbefa/EFA_HOT_Vehcat_HGV.XLS"
EF_MOT = abs_path + "/data/restricted_input/hbefa/EFA_HOT_Vehcat_MOT.XLS"
EF_ColdStart = abs_path + "/data/restricted_input/hbefa/EFA_ColdStart_Vehcat_ColdStart.XLS"