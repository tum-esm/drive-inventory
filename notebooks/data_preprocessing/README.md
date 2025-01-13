# Data Preprocessing
 Data pre-processing depends heavily on the available data and its format. A universal procedure cannot be provided at this level. However, the format in which the data must be converted for further processing is described. Use this README document as well as the comments and descriptions in the respective notebooks to assist with data pre-processing.

## 1. Pre-Processing of counting station locations
Pre-Processing of the counting station locations is a two-step approach. The first step is to clean the original input format of the location information and convert it into a standardized data format. If they are not yet referenced to the road links in the traffic model, manually add the *road_link_id* of the respective road link to the location information. We subselected couting stations in our area of interest and performed the manual referencing using [QGIS](https://www.qgis.org/).

>**_ToDo:_**
>- Clean and convert the location data to a standardized format. (Use [preprocess_mst_locations.ipynb](/notebooks/data_preprocessing/preprocess_mst_locations.ipynb) and [preprocess_bast_locations.ipynb](/notebooks/data_preprocessing/preprocess_bast_locations.ipynb) for reference.)
>- Open the cleaned locations file as well as the traffic model in a GIS software.
>- Delete useless counters (e.g. bulk of counters around event locations) as well as counters outside your region of interest.
>- Precisely allocate the detector location on the respective road link. Reference by adding the *road_link_id* to the location of the detector.

### Format of the cleaned location dataset
|Variable|Description|
|-------:|:----------|
|**road_link_id**| (Foreign Key) Reference to the respective road link of the traffic model. 
|MST_ID| Individual identifier for each individual counting station|
|DETEKTOR_ID| Individual identifier for each detector. One counting station (MST_ID) could have multiple detectors.
|FAHRTRICHTUNG (optional)| Direction of the road (simplifies allocation of the counting stations in GIS)|
|LONGITUDE| Location longitude| 
|LATITUDE| Location latitude|

## 2. Pre-Processing of the counting data
The traffic counting data can be sourced from different providers and must be converted to a unified format before further processing. Additionally, the 8+1 vehicle classification needs to be mapped to the classification available in HEBFA.

>**_ToDo:_**
>- Open, clean and convert raw counting data to the data format shown below. Use [preprocess_mst_counting_data.ipynb](/notebooks/data_preprocessing/preprocess_mst_counting_data.ipynb) and [preprocess_bast_counting_data.ipynb](/notebooks/data_preprocessing/preprocess_bast_counting_data.ipynb) for reference.

### Data format for traffic counting data
|Attribute |Description|
|---------:|:----------|
|**date** | Date of the measurement.|
|**road_link_id** | Identifies the road link in the traffic model.|
|**detector_id** |Identifier for the dectector loop (several detectors could be located on one road link)|
|**detector_type** |NaN or 8+1 |
|**vehicle_class** |PKW, LNF, SNF, MOT, BUS, SUM|
|**metric**|Volume or speed|
|**daily_value**|Daily sum value|
|**00:00**|
|...| Hourly Values|
|**23:00**|

## 3. Pre-processing for the traffic model
As soon as the traffic counting data is available, the traffic model must be pre-processed and converted into the required format. We use a macroscopic traffic model (PTV VISUM) that represents the average weekday traffic outside vacation time for Passenger Cars (PC), Light Cargo Vehicles (LCV) and Heavy Goods Vehicles (HGV). It also provides the number of vehicle starts in defined spatial areas which is used to calculate the cold start excess emissions (CSEE). First, we import the traffic model outputs and convert important attributes to HEBFA compatible formats. Additional to the actual road type, we define an attribute *scaling_road_type* that combines multiple road types for temporal scaling. Then the vehicle share correction factors are calculated and the zonal number of vehicle starts is attributed to the road links.


### Data format of the traffic model
|Attribute |Description|
|---------:|:----------|
|road_link_id| Unique identifier of the road link.| 
|road_type| HBEFA compatible type of the road. (e.g. Motorway-Nat).| 
|hour_capacity| Hourly traffic capacity of the road link.|
|lanes| Number of individual lanes of the road.| 
|hbefa_speed| HBEFA compatible maximum allowed speed on the road link.| 
|hbefa_gradient| HBEFA compatible gradient of the road.| 
|dtv_SUM| Total traffic volume for the reference time-period on the road link.|
|delta_PC| Share of passenger car traffic on the road link.
|delta_LCV| Share of light cargo vehicle traffic on the road link.| 
|delta_HGV| Share of heavy goods vehicle traffic on the road link.| 
|hgv_corr| Correction factor for heavy goods vehicles.| 
|lcv_corr| Correction factor for light cargo vehicles.| 
|PC_cold_starts| Number of passenger car vehicle starts.|
|PC_cold_starts| Number of passenger car vehicle starts.|




## 4. Combine pre-processed counting data



Final steps

- update data paths
- continue wiht the inventory calculation. -> Reference inventory readme

