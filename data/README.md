# DRIVE Data Requirements

This folder contains the required data and generated outputs of the framework. It has three folders for input data ([auxiliary](/data/auxiliary/), [geodata](/data/geodata/) and [restricted input](/data/restricted_input/)) and one for the outputs ([inventory](/data/inventory/)). Most folders are empty and currently only provide a working structure as the data is individual for each use-case and cannot be shared publicly. Please go through the following steps carefully to assemble a suitable dataset for the emission calculation.<br>

> At the end of each section, the tasks to be performed by the user are briefly summarized.

## [Restricted Input](/data/restricted_input/)
This is the most important input data folder for the inventory. It holds (1) the traffic model, (2) traffic counting data and (3) HBEFA emission factors.<br>
The traffic model must provide geoinformation about the roads and contain at least the following attributes: (1) the maximum speed allowed on the road section, (2) the road type and (3) the traffic volume for a reference period (e.g. average weekday traffic).<br>
The traffic counting data must be available from multiple counting stations located on different road types in the region of interest. The data should be available with an hourly time resolution for the whole time-period of interest and categorized by vehicle class (8+1 counting stations)<br>
Emission factors from [HBEFA 4.2](https://www.hbefa.net/) are used. It is required to get a [HBEFA Licence](https://www.hbefa.net/en/order-form) to access the database.

> **ToDo:** <br>
>- Get access to a traffic model that fullfils the requirements mentioned above.
>- Get access to vehicle-specific traffic counting data with hourly resolution. For example, the German Federal Highway Research Insititute ([bast](https://www.bast.de/EN/Home/home_node.html)) publishes traffic count data from federal roads on their [homepage](https://www.bast.de/DE/Verkehrstechnik/Fachthemen/v2-verkehrszaehlung/Stundenwerte.html;jsessionid=F3B87277CB38872C872B4A2F29A6C34A.live11292?nn=1819490). 
>- Get access to HBEFA 4.2 and follow the instructions in the [HBEFA readme document](/data/restricted_input/hbefa/README.md) on how to export the emission factors from the HBEFA MS Access application.

## [Auxiliary data](/data/auxiliary/)
Includes a **.xlsx* table with date information for all days in the timeperiod of interest. It is used to distinguish day types like working days, weekend days and holidays.

> **ToDo:** <br>
>- Fill the [excel sheet](/data/auxiliary/calender_18to23.xlsx) with information for the timeperiod of interest. More detailed instructions are available in the example sheet.

## [Geodata](/data/geodata/)
This folder holds all auxiliary geodata required for the inventory processing. The main purpose of the data is to (1) define the region of interest and (2) provide a spatial grid for rasterizing the emissions (gridding).

> **ToDo:** <br>
>- Provide a **.gpkg* file with one polygon to define your region of interest (ROI).<br> 
>- Provide a **.gpkg* file with a spatial grid for rasterizing the line source emissions. If not available, this grid can also be generated using the make_grid function in the [gridding module](/utils/gridding.py).

## [Inventory](/data/inventory/)
In the inventory folder, all outputs are stored. The subfolder [temporal_profiles](/data/inventory/temporal_profiles/) holds the corresponding time profiles.


## Final steps
For easy access to all files and folders, a data paths module translates all file- and folderpaths to variable that can be easily accessed.<br>
Continue with data preprocessing as described [here](/notebooks/data_preprocessing/README.md).

> **ToDo:** <br>
>- Update the file- and folderpaths in [data_paths.py](/utils/data_paths.py) for easy access in all subsequent steps.<br>
>- Continue with data preprocessing.
