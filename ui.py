import sys
import PySimpleGUI as sg
from preprocessing import preprocess_bast_locations
from preprocessing import preprocess_mst_locations

start_col = sg.Column(
    [
        [sg.Text("Data-driven Road-Transport Inventory for Vehicle Emissions", key="title")],
        [sg.Button("START", key="start")]
    ],
    key="-START-COL-",
    visible=True
)

preprocess_col = sg.Column(
    [
        [sg.Text("Preprocessing", key="pp_text")],
        [sg.Button("START", key="pp_start")]
    ],
    key="-PP-COL-",
    visible=False
)
layout = [[start_col, preprocess_col]]
window = sg.Window("DRIVE 1.0", layout, size=(980, 510), finalize=True)

def start_screen():
    window["-START-COL-"].update(visible=True)

    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED:
            window.close()
            return False
        if event == "start":
            window["-START-COL-"].update(visible=False)
            return True

def preprocess_screen():
    window["-PP-COL-"].update(visible=True)
    # Create an event loop
    while True:
        event, values = window.read()
        # End program if user closes window or
        # presses the OK button
        if event == sg.WIN_CLOSED:
            break
        if event == "pp_start":
            window["pp_text"].update("Preprocessing in progress...")
            if(preprocess_bast_locations.run()):
                sg.popup("Preprocessing BAST completed successfully!")
            else:
                sg.popup("Preprocessing BAST failed!")
                break
            if(preprocess_mst_locations.run()):
                sg.popup("Preprocessing MST completed successfully!")
            else:
                sg.popup("Preprocessing MST failed!")
                break
    window.close()

if __name__ == "__main__":
    if(not start_screen()):
        print("Program terminated by user.")
        sys.exit()
    preprocess_screen()
    

