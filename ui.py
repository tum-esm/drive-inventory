import sys
from unittest import case
import PySimpleGUI as sg
from preprocessing import preprocess_bast_locations
from preprocessing import preprocess_mst_locations
from enum import Enum

#States of the GUI
class State(Enum):
    EXIT = -1
    START = 0
    MAIN_MENU = 1
    PREPROCESS = 2

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
        [sg.Button("START", key="pp_start")]
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
            result = State.EXIT
            break
        if event == "start":
            result = State.MAIN_MENU
            break

    window["start_col"].update(visible=False)
    return result
        
def main_menu_screen():
    window["main_menu_col"].update(visible=True)
    result = State.EXIT

    while True:
        event, values = window.read()

        if event == sg.WIN_CLOSED:
            result = State.EXIT
            break
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
            result = State.EXIT
            break
        if event == "pp_start":
            window["pp_text"].update("Preprocessing in progress...")
            if(preprocess_bast_locations.run()):
                sg.popup("Preprocessing BAST completed successfully!")
            else:
                sg.popup("Preprocessing BAST failed!")
            if(preprocess_mst_locations.run()):
                sg.popup("Preprocessing MST completed successfully!")
            else:
                sg.popup("Preprocessing MST failed!")

    window["preprocess_col"].update(visible=False)


if __name__ == "__main__":
    state = State.START
    while True:
        if state == State.START:
            state = start_screen()
        elif state == State.PREPROCESS:
            state = preprocess_screen()
        elif state == State.MAIN_MENU:
            state = main_menu_screen()
        elif state == State.EXIT:
            break
        else:
            print("Invalid state.")
            break
    window.close()
    sys.exit()
    

