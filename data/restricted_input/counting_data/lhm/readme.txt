Here you can find all the traffic counting data we received from the city. 
The year of 2019 ist divided into four quarters since it was exported with an earlier software version form the city. 
All other files contain the counting data of all counting stations in Munich. 

The mst-location.csv file contains the raw geo-information of all counting stations. This dataset was cleaned and transformed into a geopackage which is saved as mst_locations_cleaned.gpkg in this folder.
In a next step, the cleaned locations file was imported to QGIS for furhter processing which included the following steps: 

1. A subset of all counting locations was selected as there are many in areas around the Allianz Arena and the trade fair. Some further counting staions (mainly used for traffic control purposes) were also excluded
as they are expected to not deliver useful information (e.g.: on road ramps and exits)
2. The individual detector locations were manually assigned to their respective road links of the visum model. For this, a road link id was appended to the dataset.
3. The final locations dataset is saved as mst_locations_selected.gpkg

The goal is to combine all counting data to one single large file (e.g. feather) and all location information to another file (e.g. geopackage)