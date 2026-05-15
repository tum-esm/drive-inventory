
import os
import pandas as pd
import geopandas as gpd
from utils import data_paths

expected_counting_data = {
    "road_link_id":      pd.api.types.is_float_dtype,
    "vehicle_class":     pd.api.types.is_string_dtype,
    "date":              pd.api.types.is_datetime64_any_dtype,
    "road_type":         pd.api.types.is_string_dtype,
    "complete":          pd.api.types.is_bool_dtype,
    "valid":             pd.api.types.is_bool_dtype,
    "completness":       pd.api.types.is_float_dtype,
    "scaling_road_type": pd.api.types.is_string_dtype,
    "sqv":               pd.api.types.is_float_dtype,
    "day_type":          pd.api.types.is_integer_dtype,
    "daily_value":       pd.api.types.is_float_dtype,
    **{str(i):           pd.api.types.is_float_dtype for i in range(24)},  # hourly columns 0-23
}

expected_traffic_model_format = {
    "road_link_id":       pd.api.types.is_integer_dtype,   # 'NO' column, originally int
    "road_type":          pd.api.types.is_string_dtype,    # e.g. 'Motorway-Nat'
    #"scaling_road_type":  pd.api.types.is_string_dtype,    # e.g. 'Distributor/Secondary'
    "hour_capacity":      pd.api.types.is_integer_dtype,   # 'CAPPRT' column
    "lanes":              pd.api.types.is_integer_dtype,   # 'NUMLANES' column
    "hbefa_speed":        pd.api.types.is_integer_dtype,   # snapped to HBEFA speed values
    #"speed":              pd.api.types.is_integer_dtype,   # 'V0PRT' original speed
    "hbefa_gradient":     pd.api.types.is_string_dtype,    # e.g. '+2%', '-4%'
    "dtv_SUM":            pd.api.types.is_float_dtype,   # daily traffic sum
    "delta_PC":           pd.api.types.is_float_dtype,     # share of personal cars (optional)
    "delta_LCV":          pd.api.types.is_float_dtype,     # share of light cargo vehicles (optional)
    "delta_HGV":          pd.api.types.is_float_dtype,     # share of heavy goods vehicles (optional)
    "hgv_corr":           pd.api.types.is_float_dtype,     # HGV correction factor
    "lcv_corr":           pd.api.types.is_float_dtype,     # LCV correction factor
    "PC_cold_starts":     pd.api.types.is_float_dtype,     # distributed cold starts PC (optional)
    "LCV_cold_starts":    pd.api.types.is_float_dtype,     # distributed cold starts LCV (optional)
}

def check_restricted_input():
    traffic_model = os.path.isfile()
    counting_data = False
    emission_factors = False
    return (traffic_model, counting_data, emission_factors)

def check_auxiliary_data():
    return (False)

def check_geodata():
    return (False, False)

def check_cleaned_location_dataset():
    return False

def check_traffic_model(file_path = ""):
    try:
        df = gpd.read_file(file_path)
    except Exception as e:
        print(f"Error reading traffic model file: {e}")
        return False
    for col, dtype_fun in expected_traffic_model_format.items():
        if col not in df.columns:
            print(f"Missing column: {col}")
            if(col in ["delta_PC", "delta_LCV", "delta_HGV", "PC_cold_starts", "LCV_cold_starts"]):
                print(f"Note: Column {col} is optional and can be added later. Continuing with the check.")
                continue
            return False
        if not dtype_fun(df[col]):
            print(f"Incorrect dtype for column: {col}")
    print("OK")
    return True

def check_counting_data(file_path = ""):
    try:
        df = pd.read_parquet(file_path)
    except Exception as e:
        print(f"Error reading counting data file: {e}")
        return False
    #df.info()
    for col, dtype_fun in expected_counting_data.items():
        if col not in df.columns:
            print(f"Missing column: {col}")
            return False
        if not dtype_fun(df[col]):
            print(f"Incorrect dtype for column: {col}")
            return False
    print("OK")
    return True

def check_emission_factors():
    return False

if __name__ == "__main__":
    check_counting_data()
    check_traffic_model()
