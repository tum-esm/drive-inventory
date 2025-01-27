# Emission Calculation
At this point you should have already fulfilled all [data requirements](/data/README.md) and [pre-processed the input data](/notebooks/data_preprocessing/README.md). This allows you to easily use the notebooks in this folder to calculate total emissions of different species, their spatial and temporal distribution and estimate uncertainties based on the traffic counting data.<br>

Set-up and run the notebooks in the following order:<br>
- [01_optimize_VCR_thresholds.ipynb](/notebooks/01_optimize_VCR_thresholds.ipynb): Optimize volume capacity ratio thresholds to more accurately represent the traffic condition.
- [02_calculate_total_VKT.ipynb](/notebooks/02_calculate_total_VKT.ipynb): Calculate and visualize the total vehicle kilometers travelled and annual changes of the VKT and the traffic condition.
- [11_calculate_cold_emissions.ipynb](/notebooks/11_calculate_cold_emissions.ipynb): Calculate cold-start excess emissions and respective timeprofiles.
- [12_calculate_hot_emissions.ipynb](/notebooks/12_calculate_hot_emissions.ipynb): Calculate hot exhaust vehicle emissions and respective timeprofiles.
- (Optional) [13_calculate_detector_emissions.ipynb](/notebooks/13_calculate_detector_emissons.ipynb): Calculate emissions at a individual traffic counting detector level for subsequent uncertainty estimation. 
- (Optional) [21_emission_gridding.ipynb](/notebooks/21_emission_gridding.ipynb): Combine cold-start and hot-exhaust emissions and rasterize the line-source emissions.

Detailed instructions are available in the respective notebook. Change the input parameters according to your application in the section **notebook_settings** of the respective notebook.

## Plotting
The [plotting folder](/notebooks/plotting/) includes various notebooks that are used to visualize and analyze model outputs. These are application specific and can be used for reference. 