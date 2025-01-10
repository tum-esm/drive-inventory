# Data folder

This folder contains the data required to process the emission inventory. Since not all data are publicly available (e.g. VISUM model and traffic counting data), there are some datasets missing. <br><br>

## Auxiliary data
Includes the calendar excel file used to distinguish between different day types.

## Geodata
Included publicly available geodata and processed geodata that is used for gridding or to define a region of interest. 

## Restricted Input --> not published
Here, the VISUM model data and traffic counting data and HBEFA emission facators are saved which cannot be shared publicly. 

## Inventory
Contains the final products including the gridded inventory and timeprofiles. 




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