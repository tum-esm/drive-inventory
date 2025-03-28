# Data-driven Road-Transport Inventory for Vehicle Emissions (DRIVE)<br>

Python-based framework to calculate road traffic emissions in urban areas. The method is based on a multi-modal macroscopic traffic model (static traffic demand model) and data from multiple vehicle-specific traffic counting stations (dynamic traffic data) to estimate hourly traffic volume and traffic condition on a road-link level. This granular activity data is combined with [HBEFA 4.2](https://www.hbefa.net/) emission factors to estimate hot vehicle exhaust emissions and cold start excess emissions.
In conclusion, this framework provides methods to...<br><br>
... estimate and generate a high-resolution spatial emission map for road transport emissions.<br>
... generate accurate, data-based temporal profiles for greehouse gases and air pollutants.<br>
... conduct a data-based uncertainty analysis of the activity data and resulting emission estimate.

The project is part of [**ICOS Cities**](https://www.icos-cp.eu/projects/icos-cities), funded by the European Union's Horizon 2020 Research and Innovation Programme under grant agreement No. **101037319**.

<br>

<img src="./docs/img/method_overview.svg">

## How to use DRIVE

> **_IMPORTANT:_** Comprehensive data availability is fundamental when using this framework. Please check if you can fulfill all data requirements listed in the [data folder](/data/README.md) first. <br>


### IDE Setup
`uv`is used for dependency management in this project. Make sure you have uv installed on your device ([installation instruction](https://docs.astral.sh/uv/getting-started/installation/))<br>
To set up the project and create a virtual environment run `uv sync`. Make sure, run all scripts and notebooks in the respective environment.

### Application
When the data requirements are fulfilled and the IDE is running, please refer to the [notebooks folder](/notebooks/README.md) for further instructions.<br>


## Related Work
Kühbacher, D., Aigner, P., Super, I., Droste, A., Denier van der Gon, H., Ilic, M., and Chen, J.: Bottom-up estimation of traffic emissions in Munich based on macroscopic traffic simulation and counting data, EGU General Assembly 2023, Vienna, Austria, 24–28 Apr 2023, EGU23-12997, https://doi.org/10.5194/egusphere-egu23-12997, 2023.

## Contributors
Daniel Kühbacher (Lead) [@DanielKuebi](https://github.com/DanielKuebi)<br>
Ali Ahmand Khan [@alimayo](https://github.com/orgs/tum-esm/people/alimayo)<br>
Julian Bärtschi [@jbaertschi](https://github.com/jbaertschi)
