import sys
from unittest import case
import PySimpleGUI as sg
from preprocessing import preprocess_bast_locations
from preprocessing import preprocess_mst_locations
from preprocessing import preprocess_2025_visum_model
from preprocessing import preprocess_mst_counting_data
from preprocessing import combine_preprocessed_files
from preprocessing import preprocess_bast_counting_data

from enum import Enum

#States of the GUI
class State(Enum):
    EXIT = -1
    START = 0
    MAIN_MENU = 1
    DATA_REQ = 2
    PREPROCESS = 3

# Definiition of the different columns for the different screens of the GUI
start_col = sg.Column(
    [
        [sg.Text("Data-driven Road-Transport Inventory for Vehicle Emissions", key="title")],
        [sg.Button("START", key="start")]
    ],
    key="start_col",
    visible=True
)

main_menu_col = sg.Column(
    [
        [sg.Text("Main Menu", key="main_menu_title")],
        [sg.Text("1. Data Requirements", key="main_menu_data_req")],
        [sg.Text("2. Data Preprocessing", key="main_menu_data_preprocess"), sg.Button("Go", key="mm_preprocess")],
        [sg.Button("Exit", key="main_menu_exit")]
    ],
    key="main_menu_col",
    visible=False
)

preprocess_col = sg.Column(
    [
        [sg.Text("Preprocessing", key="pp_text")],
        [sg.Button("START", key="pp_start")],
        [sg.ProgressBar(6, key='pp_progress_bar', visible=False)],
        [sg.Button("Return to main menue", key='pp_return')]
    ],
    key="preprocess_col",
    visible=False
)
layout = [[start_col, preprocess_col, main_menu_col]]

# Window definition
window = sg.Window("DRIVE 1.0", layout, size=(980, 510), finalize=True, resizable=True)

# Definition of the different screens of the GUI
def start_screen():
    window["start_col"].update(visible=True)
    result = State.EXIT

    while True:
        event, values = window.read()
        
        if event == sg.WIN_CLOSED:
            return
        if event == "start":
            result = State.MAIN_MENU
            break

    window["start_col"].update(visible=False)
    return result

def data_requirements_screen():
    result = State.EXIT
    return result

def main_menu_screen():
    window["main_menu_col"].update(visible=True)
    result = State.EXIT

    while True:
        event, values = window.read()

        if event == sg.WIN_CLOSED:
            return
        if event == "main_menu_exit":
            result = State.EXIT
            break
        if event == "mm_preprocess":
            result = State.PREPROCESS
            break

    window["main_menu_col"].update(visible=False)
    return result

def preprocess_screen():
    window["preprocess_col"].update(visible=True)
    result = State.EXIT

    while True:
        event, values = window.read()

        if event == sg.WIN_CLOSED:
            return State.EXIT
        if event == "pp_return":
            result = State.MAIN_MENU
            break
        if event == "pp_start":
            count = 0
            window["pp_text"].update("Preprocessing in progress...")
            window["pp_progress_bar"].update(visible=True)

            if(preprocess_bast_locations.run()):
                count += 1
                window["pp_progress_bar"].update(current_count=count)
                if(preprocess_mst_locations.run()):
                    count += 1
                    window["pp_progress_bar"].update(current_count=count)
                    if(preprocess_bast_counting_data.run()):
                        count += 1
                        window["pp_progress_bar"].update(current_count=count)
                        if(preprocess_mst_counting_data.run()):
                            count += 1
                            window["pp_progress_bar"].update(current_count=count)
                            if(preprocess_2025_visum_model.run()):
                                count += 1
                                window["pp_progress_bar"].update(current_count=count)
                                if(combine_preprocessed_files.run()):
                                    count += 1
                                    window["pp_progress_bar"].update(current_count=count)                                    
                                else:
                                    sg.popup("Combining preprocessed files failed")
                            else:
                                sg.popup("Preprocessing Visum model failed")
                        else:
                            sg.popup("Preprocessing MST counting data failed")
                    else:
                        sg.popup("Preprocessing BAST counting data failed")
                else:
                    sg.popup("Preprocessing MST failed!")
            else:
                sg.popup("Preprocessing BAST failed!")

            if(count == 6):
                sg.popup("Preprocessing completed successfully!")
            window["pp_progress_bar"].update(current_count=0)
            window["pp_progress_bar"].update(visible=False)
            window["pp_text"].update("Preprocessing")


    window["preprocess_col"].update(visible=False)
    return result

if __name__ == "__main__":
    state = State.START
    while True:
        if state == State.EXIT:
            break
        elif state == State.START:
            state = start_screen()
        elif state == State.MAIN_MENU:
            state = main_menu_screen()
        elif state == State.DATA_REQ:
            state = data_requirements_screen()
        elif state == State.PREPROCESS:
            state = preprocess_screen()
        else:
            print("Invalid state.")
            break
    window.close()
    sys.exit()
    
