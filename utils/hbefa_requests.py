from dotenv import dotenv_values
import requests
import json
import time
import re
import base64
import pandas as pd
from io import StringIO

def request_hbefa(emcat="hot", yearref="2024", agglevel_ts="aggregate_ts"):
    # Load credentials from .env file
    mail = dotenv_values(".env").get("HBEFA_EMAIL")
    password = dotenv_values(".env").get("HBEFA_PASSWORD")
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
        "pollutant": "NOx,FC,CO2(rep),CO2(total),NO2,CH4,NMHC,Pb,SO2,Benzene,HC,CO,CO2e,PM10-ex,PM2.5-ex,PN23-ex,BC-ex",
        "emcat": emcat,
        "hbversion_int": "501006",
        "agglevel_ts": agglevel_ts,
        "idvehcat": "1,2", # 1= PC, 2=LCV, 3=HGV, 4=Coach, 5=Bus, 6=Motorcycle
        "wgt": "True",
        "idtraffic_scen": "48",
        "idtsgrad": "524",
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
        "calc_wtt": "False",
        "idenergymix_scen": "3"
    }

    response = session.post(f"{BASE_URL}/efa-async", json=payload)
    print("Job submitted:", response.status_code)
    print("Job response:", response.text)

    # Poll for result
    task_id = response.json().get("task_id")
    for i in range(30):
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
            df.to_json('test.json')
            df.to_csv('test.csv', index=True, index_label="index")
            df.to_parquet(f'{yearref}_{emcat}_{agglevel_ts}.parquet', index=True)
            break

        time.sleep(3)
    else:
        print("Timed out waiting for result")
# Press the green button in the gutter to run the script.

#if __name__ == "__main__":
#    request_hbefa()