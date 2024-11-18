# Processing Utils and Interfaces
This folder contains user-defined functions and classes that are used in the calculation of the traffic emission inventory. It contains data paths, interfaces for more convenient access to files and functions/classes for processing.

[Data Paths](data_paths.py)<br>
Contains absolute paths to all files and folders that are required as input for the stock calculation and for saving the output.

[Excel Calendar](excel_calendar.py)<br>
Interface to a predefined Excel table (*.xlsx) containing calendar information for each day of the desired period. Public holidays and holiday periods are often local events and cannot be defined universally.

[Gridding](gridding.py)<br>
Utility function for converting emissions from line sources, as output by the traffic emission calculation, into gridded emissions. Users can specify a predefined grid or specify the grid in the function.

[Hot Emission Calculation](hbefa_hot_emissions.py)<br>
Emission calculation module for hot exhaust emissions. Imports hot exhaust emission factors from a *.csv file, calculates traffic situations based on the volume capacity ratio (VCR) and calculates hourly/daily emissions for different vehicle classes and components. Further information can be found in the documentation within the file.

[Hot Emission Process](hot_emission_process.py)<br>
Implements the *Hot Emission Calculation* function and adds a queing functionality that can be used in a mutliprocessing setup.

[Cold Start Excess Emission Calculation](hbefa_cold_emissions.py)<br>
Emissions calculation module for excess cold start emissions (CSEE). Imports cold start emission factors from a *.csv file and calculates the CSEE hourly based on the number of vehicle starts and the ambient temperature. Note that excess emissions can also be negative. For example, NOx emissions are higher at high temperatures, so total emissions are lower during cold starts.

[Traffic Counts](traffic_counts.py)<br>
Loads pre-processed traffic count data, calculates annual scaling factors, modal split and daily cycles. Provides a function for filling gaps in annual profiles and vehicle shares.