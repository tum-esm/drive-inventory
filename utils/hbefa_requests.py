import os
from dotenv import dotenv_values
import requests
import json
import time
import re
import base64
import pandas as pd
from io import StringIO
from utils import data_paths

# Parameters:
# emcat: emission category (hot, start, evap-soaked, evap-diurnal, evap-lr)
# yearref: reference year for emission factors e.g. 2024
# agglevel_ts: aggregation level for traffic situation (aggregate_ts, single_ts, static_ts)
def request_hbefa(emcat="hot", yearref="2024", agglevel_ts="aggregate_ts"):
    """
    Request HBEFA emission factors for specific parameters and save results as parquet file. Requires valid HBEFA credentials stored in .env file.
    Args:
        emcat: The emission category: "hot", "start", "evap-soaked", "evap-diurnal", "evap-lr".
        yearref: The reference year, e.g. "2024".
        agglevel_ts: The aggregation level: "aggregate_ts", "single_ts", "static_ts".

    Returns:
        None. Saves the requested emission factors as a parquet file in the specified path.
    """
    #Check if file already exists
    filename = f'{data_paths.EF_PATH}{yearref}_{emcat}_{agglevel_ts}.parquet'
    if os.path.exists(filename):
        print(f"File {filename} already exists. Skipping request.")
        return

    # Load credentials from .env file
    mail = dotenv_values(data_paths.ENV_PATH).get("HBEFA_EMAIL")
    password = dotenv_values(data_paths.ENV_PATH).get("HBEFA_PASSWORD")
    print("Loaded credentials for:", mail)
    print("Password length:", len(password) if password else "No password found")
    BASE_URL = "https://hbefa-server-repo.azurewebsites.net"
    session = requests.Session()
    get_response = session.get(f"{BASE_URL}/login")

    # Get CSRF token directly from the form HTML (more reliable)
    csrf_token = re.search(r'id="csrf_token" name="csrf_token".*?value="(.*?)"', get_response.text).group(1)
    print("CSRF token:", csrf_token)

    login_response = session.post(
        f"{BASE_URL}/login",
        data={
            "email": mail,
            "password": password,
            "csrf_token": csrf_token,
            "submit": "Login"
        },
        headers={"X-CSRFToken": csrf_token, "Referer": f"{BASE_URL}/login"}
    )

    print("Login status:", login_response.status_code)
    print("Session cookie:", session.cookies.get("session")[:40], "...")

    # Now submit the job using the session
    payload = {
        "country": "D",
        # Pollutants: HC, CO, NOx, NO2, CO2(rep), CO2(total), PM10-ex, PN23-ex,
        # CH4, NHMC, Pb, SO2, N2O, NH3, Zn-ex, Zn-nx, Cd-ex, Cd-nx, PM10-nx,
        # Benzene, Toluene, Xylene, FC, EC, PM2.5-ex, BC-ex, PM2.5-nx, BC-nx,
        # CO2e, WE-pos, HCHO, CH3CHO, HNCO, HNO2, PM10-nx-tyre, PM10-nx-brake,
        # PM10-nx-road, PM10-nx-resusp, PM2.5-nx-tyre, PM2.5-nx-brake,
        # PM2.5-nx-road, PM2.5-nx-resusp, PN23-nx-brake, PN23-nx-road,
        # PN23-nx-resusp, PN23-nx
        "pollutant": "CO,NOx,NO2,CO2(rep),CO2(total),PM10-ex,CH4,PM10-nx,PM2.5-ex,BC-ex,PM2.5-nx,BC-nx",
        "emcat": emcat,
        "hbversion_int": "501006",
        "agglevel_ts": agglevel_ts,
        #"idvehcat": "1",
        "idvehcat": "1,2,14,6,9", #TODO -> Check values: 1= PC, 2=LCV, 3=HGV, 4=Coach, 5=Bus, 6=Motorcycle
        "wgt": "True", # Whether to weight emission factors by fleet composition (True/False).
        "idtraffic_scen": "48",
        # Aggregated traffic situation pattern: idtsgrad
        # For Germany:
        # --- Current (UBA) ---
        #   521: D Ø-MW UBA 2024        (Motorway only)
        #   522: D Ø-Rural UBA 2024     (Rural only)
        #   523: D Ø-Urban UBA 2024     (Urban only)
        #   524: D Ø UBA 2024           (All road categories)
        #
        #   421: D Ø-MW UBA 2023
        #   422: D Ø-Rural UBA 2023
        #   423: D Ø-Urban UBA 2023
        #   424: D Ø UBA 2023
        #
        #   332: D Ø UBA 2022
        #   333: D Ø-MW UBA 2022
        #   334: D Ø-Rural UBA 2022
        #   335: D Ø-Urban UBA 2022
        #
        #   221: D Ø-MW UBA 2021
        #   222: D Ø-Rural UBA 2021
        #   223: D Ø-Urban UBA 2021
        #   224: D Ø UBA 2021
        #   324: D Ø UBA 2021 detailed
        #   328: D Ø-MW UBA 2021 korr
        #   329: D Ø-Rural UBA 2021 korr
        #   330: D Ø-Urban UBA 2021 korr
        #   331: D Ø UBA 2021 korr
        #
        # --- Outdated (IFEU, Nov 2009) ---
        #   121: Germany Motorway
        #   122: Germany Rural
        #   123: Germany Urban
        #   124: Germany all Road Categories
        "idtsgrad": "523",
        "yearref": yearref,
        "agglevel_fleet": "vehcat",
        "agglevel_energy": "none",
        "nocorr": "False",
        "lang": "en",
        "col_selection": "standard",
        "col_titles": "speaking",
        "load_in_rows": "False",
        "agg_cols": "False",
        "verbose": "False",
        "test_outputs": "False",
        "calc_wtt": "True", #Doesn't exist for HBEFA 5.1, but doesn't cause an error if included in the request
        "idenergymix_scen": "3",
        # Available road gradients (idgrad):
        # 30: 0%
        # 32: +/-2%
        # 34: +/-4%
        # 36: +/-6%
        # 54: -6%
        # 56: -4%
        # 58: -2%
        # 62: +2%
        # 64: +4%
        # 66: +6%
        #"idgrad": "30,54,56,58,62,64,66",
        # Available traffic scenarios (idtraffic_scen):
        "idarea": "2",
        #   1: Rural
        #   2: Urban
        #
        # idroadtype (road type):
        "idroadtype":"10,20,21,30,40,50",
        #   10: Motorway-Nat.
        #   11: Motorway-City
        #   12: Semi-Motorway
        #   20: Primary-nat. non-motorway
        #   21: Primary-city non-motorway
        #   30: Distributor/Secondary
        #   31: Distributor/Secondary (sinuous)
        #   40: Local/Collector
        #   41: Local/Collector (sinuous)
        #   50: Access-residential
        #
        # idspeedlimit (speed limit in km/h):
        #   03: 30,  04: 40,  05: 50,  06: 60,  07: 70,  08: 80
        #   09: 90, 10: 100, 11: 110, 12: 120, 13: 130, 14: >130
        #
        # idlos (level of service):
        #   1: Freeflow
        #   2: Heavy
        #   3: Saturated
        #   4: Stop+go
        #   5: Stop+go_II
        #
        # Example: 110081 -> area=Rural, Motorway-Nat., speedlimit=80, LOS=Freeflow
        #"idts": "110081,110082",
        # Available ambient condition patterns (idpatternambientcond):
                # --- Simple patterns (averaged dimensions) ---
        # ID  : label                  : description
        #   1 : ØGermany               : Ø trip lengths, Ø parking times
        #  11 : Ø/spring               : Ø trip lengths, Ø parking times
        #  12 : Ø/summer               : Ø trip lengths, Ø parking times
        #  13 : Ø/autumn               : Ø trip lengths, Ø parking times
        #  14 : Ø/winter               : Ø trip lengths, Ø parking times
        #  14 : Ø/winter               : Ø trip lengths, Ø parking times
        #  20 : Øgermany (imported)    : from UBA/HBEFA country data template
        #  21 : Ø/spring (imported)    : from UBA/HBEFA country data template
        #  22 : Ø/summer (imported)    : from UBA/HBEFA country data template
        #  23 : Ø/autumn (imported)    : from UBA/HBEFA country data template
        #  24 : Ø/winter (imported)    : from UBA/HBEFA country data template
        #  25 : Øgermany (imported v4) : from UBA/HBEFA country data template
        #  30 : Øgermany (imported v4) : from UBA/HBEFA country data template
        #
        # --- Selected trip length only (Ø temp, Ø parking) ---
        # 211: TØ, tØ, 0-1km
        # 212: TØ, tØ, 1-2km
        # 213: TØ, tØ, 2-3km
        # 214: TØ, tØ, 3-4km
        # 215: TØ, tØ, >20km
        #
        # --- Selected parking time only (Ø temp, Ø trip length) ---
        # 251: TØ, 0-1h,  dØ
        # 252: TØ, 1-2h,  dØ
        # 253: TØ, 2-3h,  dØ
        # 254: TØ, 3-4h,  dØ
        # 255: TØ, 4-5h,  dØ
        # 256: TØ, 5-6h,  dØ
        # 257: TØ, 6-7h,  dØ
        # 258: TØ, 7-8h,  dØ
        # 259: TØ, 8-9h,  dØ
        # 260: TØ, 9-10h, dØ
        # 261: TØ, 10-11h,dØ
        # 262: TØ, 11-12h,dØ
        # 263: TØ, >12h,  dØ
        #
        # --- Selected parking time AND trip length (Ø temp) ---
        # Format: 3XY where X = parking time bin, Y = trip length bin
        # 311-343: TØ, parking 0-1h .. >12h, trip 0-1km
        # 331-343: TØ, parking 0-1h .. >12h, trip 1-2km
        # (pattern continues for all combinations)
        #
        # --- Fixed temperature + averaged other dims (1Temp) ---
        # IDs ~9901-10251, step 50 per temperature:
        #  9901: T-10°C, tØ, dØ
        #  9951: T-5°C,  tØ, dØ
        # 10001: T+0°C,  tØ, dØ
        # 10051: T+5°C,  tØ, dØ
        # 10101: T+10°C, tØ, dØ
        # 10151: T+15°C, tØ, dØ
        # 10201: T+20°C, tØ, dØ
        # 10251: T+25°C, tØ, dØ
        #
        # --- Full pattern: fixed temp + parking time + trip length ---
        # IDs 11XXX: combination of temperature, parking time bin, and trip length bin
        # Format: 11 {temp_idx} {parking_idx} {trip_idx}
        #
        # Temperature index:  3=+20°C, 5=+10°C, 7=0°C, 9=-10°C
        # Parking time index: 1=0-1h, 2=1-2h, 3=2-3h, 4=3-4h, 5=4-5h, 9=>12h
        # Trip length index:  1=0-1km, 2=1-2km, 3=2-3km, 4=3-4km, 5=4-5km, 9=>5km (or N/A)
        #
        # Examples:
        # 11311: temp_idx=3 (+20°C), parking_idx=1 (0-1h),  trip_idx=1 (0-1km)
        # 11711: temp_idx=7 (  0°C), parking_idx=1 (0-1h),  trip_idx=1 (0-1km)
        # 11911: temp_idx=9 (-10°C), parking_idx=1 (0-1h),  trip_idx=1 (0-1km)
        # 11319: temp_idx=3 (+20°C), parking_idx=1 (0-1h),  trip_idx=9 (N/A or >5km)
        # 11999: temp_idx=9 (-10°C), parking_idx=9 (>12h),  trip_idx=9 (>5km)
        "idpatternambientcond": "9901,9951,10001,10051,10101,10151,10201,10251", # Ambient conditions: 8 temperature levels from -10°C to +25°C (in 5°C steps),each with average parking time and average trip length (tØ/dØ)
    }

    response = session.post(f"{BASE_URL}/efa-async", json=payload)
    print("Job submitted:", response.status_code)
    print("Job response:", response.text)

    # Poll for result
    task_id = response.json().get("task_id")
    for i in range(500):
        result = session.get(f"{BASE_URL}/efa-async/{task_id}")
        print(f"Poll {i + 1}: {result.status_code} - {result.text[:100]}")

        data = result.json()
        status = data.get("status", "")

        # Keep polling while task is queued or running
        if result.status_code == 200:
            print("Raw result:")
            print(data)
            emission_factors = data.get("Emission factors")
            print(emission_factors)
            df = pd.read_json(StringIO(emission_factors))
            #df.to_json('test.json')
            #df.to_csv('test.csv', index=True, index_label="index")
            df.to_parquet(f'{filename}', index=True)
            break
        if result.status_code != 202:
            print("Error retrieving result:", result.status_code, result.text)
            break
        time.sleep(3)
    else:
        print("Timed out waiting for result")
# Press the green button in the gutter to run the script.

if __name__ == "__main__":
    request_hbefa("start", "2024", "single_ts")
    #t1 =pd.read_parquet(f'{data_paths.EF_PATH}2024_hot_aggregate_ts.parquet')
    #t1.info()
    #t2 = pd.read_parquet(f'{data_paths.EF_PATH}2024_hot_aggregate_ts2.parquet')
    #t2.info()