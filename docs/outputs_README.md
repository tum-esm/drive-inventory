# Outputs of `drive run`

`drive run <config>` (and `scripts/run_series.py`) writes the results of one run to `paths.results` (`data/inventory/v2`, the series to `.../series`). The file names carry `<stem> = <traffic model>_<year>_hbefa<version>_batch<store batch>`. In `hot_mode: aggregated`, the hot files and the GeoPackage get the suffix `_aggregated`.

| File | Content | Unit |
|---|---|---|
| `linesource_<stem>.gpkg` | Line sources: layer `hot` and layer `cold`, one feature per link piece inside the clip area, with geometry (EPSG:25832), `road_link_id`, `from_node`, `piece`, `road_type`, `scaling_road_type`, `length_km` and one column per `<vehicle class>_<component>` | g/km over the year |
| `summary_<stem>.csv` | Totals per `kind` (hot, cold), `road_type`, `vehicle_class` and `component` | t over the year |
| `grid_<name>_<stem>.gpkg` | Gridded emissions on each grid in `outputs.grids`: layers `hot`, `cold` and `total` (hot + cold), one polygon per cell (EPSG:25832) with the cell id and one column per component, summed over the vehicle classes. Every cell of the grid is kept, zeros included | kg over the year |
| `hot_<stem>.parquet`, `cold_<stem>.parquet` | The line-source tables without geometry | g/km over the year |
| `hot_profile_<stem>.parquet` | Hourly emissions per road type, vehicle class and component (local wall-clock time) | g per hour |
| `cold_profile_<stem>.parquet` | Hourly cold start emissions per vehicle class and component | g per hour |
| `hot_timeprofile_<stem>.csv`, `cold_timeprofile_<stem>.csv` | Hourly scaling factors of the profiles | – |

All products add up to the same totals. The sum of g/km × `length_km` over the line sources equals the summary and the sum of the hourly profile.

**Line-source layers:**

- **Link pieces:** a link that crosses the clip boundary (VG250, `run.clip_ags`) appears as one piece per part inside it.
- **Cold starts:** only Access-residential, Local/Collector and Distributor/Secondary links get cold start emissions. The others are 0 in the `cold` layer.
- **Vehicle classes:** the `hot` layer has PC, LCV, HGV, BUS and MOT. The `cold` layer has PC and LCV.

The size is about 45 MB per run for Munich.

## Gridding

The gridding is in `drive/domain/gridding.py` (spec R12b, port of v1's `GriddingEngine.overlay_grid`). Every line is cut at the cell borders. The part inside a cell adds g/km × its length to that cell. The grid is reprojected to the CRS of the line sources.

- **Same as v1:** on the same line sources, every cell matches v1's engine within 1e-11 kg. v1 assigned each cut piece to the cell containing its centroid; v2 computes the length inside each cell directly.
- **Grids in the Munich config:**

  | Name | File | Cells | CRS of the file | Cell id |
  |---|---|---|---|---|
  | `100m` | `geodata/TNO_100m_grid_munich.gpkg` | 32,600 | EPSG:4326 | `locationcode` |
  | `1km` | `geodata/TNO_1km_grid_munich.gpkg` | 326 | EPSG:4326 | `locationcode` |

- **Coverage:** `drive run` prints how much CO2(rep) of the line sources falls inside each grid. In 2025 it is 100.00 % on both grids, and the grid total equals the line-source total within 1e-13.
- **Runtime:** about 2 s for both grids.

The dominant road type per cell, an option in v1, is not produced. Totals per vehicle class are in the line sources and the summary.

Another grid can be added under `outputs.grids` in the config, with `path` (relative to `paths.data_root`) and `cell_id`.
