# Data Preprocessing
 Data pre-processing depends heavily on the available data and its format. A universal procedure cannot be provided at this level. However, the format in which the data must be converted for further processing is described. Use this README document as well as the comments and descriptions in the respective notebooks to assist with data pre-processing.

## 1. Pre-Processing of counting station locations
Pre-Processing of the counting station locations is a two-step approach. The first step is to clean up the original input format of the location information and convert it into a standardized data format.

>**_ToDo:_** <br>
- Clean and convert the location data to a standardized format.
- 

### Format of the cleaned location dataset
|Variable|Description|
|-------:|:----------|
|MST_ID| Individual identifier for each individual counting station|
|DETEKTOR_ID| Individual identifier for each detector. One counting station could consist of multiple detectors.
|FAHRTRICHTUNG| Direction of the road (simplifies allocation of the counting stations)|
|LONGITUDE| Location longitude| 
|LATITUDE| Location latitude|

### Format of the allocated location dataset
|Variable|Description|
|-------:|:----------|
|MST_ID| Individual identifier for each individual counting station|
|DETEKTOR_ID| Individual identifier for each detector. One counting station could consist of multiple detectors.
|FAHRTRICHTUNG| Direction of the road (simplifies allocation of the counting stations)|
|LONGITUDE| Location longitude| 
|LATITUDE| Location latitude|

