# Data folder

This folder contains the required data and generated outputs of the framework. It has three folders for input data ([auxiliary](/data/auxiliary/), [geodata](/data/geodata/) and [restricted input](/data/restricted_input/)) and one for the outputs ([inventory](/data/inventory/)). Most folders are empty and currently only provide a working structure as the data is individual for each use-case and often cannot be share publicly. Please go through the following steps carefully to assemble a suitable dataset for the emission calculation.<br>

> At the end of each section the tasks the user is intended to conduct are brifly summarized for reference.

## Auxiliary data
Includes the calendar excel file used to distinguish between different day types.

> **_Task:_** Generate the text excel 

## Geodata
Included publicly available geodata and processed geodata that is used for gridding or to define a region of interest. 

## Restricted Input --> not published
Here, the VISUM model data and traffic counting data and HBEFA emission facators are saved which cannot be shared publicly. 

## Inventory
Contains the final products including the gridded inventory and timeprofiles. 


-> make data_paths file


Main couting dataset: 

- **date** --> date of the measurement
- **road_link_id** --> identifies the road link in the traffic model (manual work)
- **road_type** --> highway, city highway, 
- **detector_id** --> identifier for the dectector loop (several detectors could be)
- **detector_type** --> NaN or 8+1 
- **vehicle_type** --> PKW, LNF, SNF, MOT, BUS
- **metric** --> volume or speed
- **daily_value** --> daily sum value
- **00:00**
- .
- . 
- . 
- **23:00** --> (hourly values)





## How to use
Data availability is essential to use this framework and calculate the road traffic emissions. 



Be aware that the followig data requirements must be fulfilled: 

- Geo-data of the road network including information of the (1) traffic volume, (2) road type, (3), maximum allowed speed and (4) road gradient. This data can typically be exported from macroscopic traffic demand models (e.g. PTV VISUM) that are commonly used by public authorities for traffic planning. The number of vehicle starts can also be exported from these models and is required to calculate cold start excess emissions (CSEE).
- Traffic counting data from multiple counting stations in your area of interest. 
- HBEFA 4.2 licence
-> provide a polygon defining your exact area of interst




required licences: 
HBEFA 4.2