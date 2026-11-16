# Outputs of `drive run`

`drive run <config>` (and `scripts/run_series.py`) writes the results of one run to `paths.results` (`data/inventory/v2`, the series to `.../series`). The file names carry `<stem> = <traffic model>_<year>_hbefa<version>_batch<store batch>`. In `hot_mode: aggregated`, the hot files and the GeoPackage get the suffix `_aggregated`.

| File | Content | Unit |
|---|---|---|
| `linesource_<stem>.gpkg` | Line sources: layer `hot` and layer `cold`, one feature per link piece inside the clip area, with geometry (EPSG:25832), `road_link_id`, `from_node`, `piece`, `road_type`, `scaling_road_type`, `length_km` and one column per `<vehicle class>_<component>` | g/km over the year |
| `summary_<stem>.csv` | Totals per `kind` (hot, cold), `road_type`, `vehicle_class` and `component` | t over the year |
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

Gridded products follow in step R12b (spec R12).
