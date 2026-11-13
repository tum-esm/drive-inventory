"""Compare the distribution of vehicle starts to links with v1 notebook 11.

Usage: uv run python scripts/compare_v1_starts.py [configs/munich_2025.yaml]

For each traffic model: v1's loop over zones (copied from notebook 11) on v1's GeoPackages, against
domain.cold_start on the store. Rows are compared in order (the store keeps v1's row order, see
compare_v1_visum.py). Also compares the daily starts within the clip boundary, which v1 computes as
starts per metre times the clipped length.
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

from drive.config import load_config
from drive.pipeline import clip_links, load_clip_boundary, load_link_starts

RTOL = 1e-9  # v1 adds zone by zone, v2 sums per link: only the order of the sums differs


def v1_starts(links: gpd.GeoDataFrame, zones: gpd.GeoDataFrame, vehicle_types: list[str], road_types: list[str],
              buffer_m: float) -> gpd.GeoDataFrame:
    """Notebook 11, 'Distribute cold starts', unchanged except for the parameters."""
    visum_links = links.copy()
    for vehicle_type in vehicle_types:
        visum_links[f'{vehicle_type}_cold_starts'] = 0.0
        for _, row in zones.iterrows():
            geometry = gpd.GeoDataFrame(geometry=[row.geometry.buffer(buffer_m)], crs=25832)
            combined = gpd.sjoin(geometry, visum_links, how='right', predicate='intersects').dropna()
            combined = combined[combined['road_type'].isin(road_types)]
            sum_dtv = combined['dtv_SUM'].sum()
            cs = visum_links.loc[combined.index, 'dtv_SUM'] * row[f'{vehicle_type}_starts'] / sum_dtv
            visum_links.loc[combined.index, f'{vehicle_type}_cold_starts'] += cs
        visum_links[f'{vehicle_type}_starts_per_meter'] = \
            visum_links[f'{vehicle_type}_cold_starts'] / visum_links['geometry'].length
    return visum_links


def clipped_daily(links: gpd.GeoDataFrame, column: str, boundary) -> float:
    """Daily starts within the boundary: starts per metre times the clipped length (v1)."""
    per_meter = links[column] / links.length
    clipped = clip_links(links.assign(_per_meter=per_meter), boundary)
    return float((clipped['_per_meter'] * clipped.length).sum())


def main(config_path: str) -> int:
    config = load_config(config_path)
    if config.run is None or config.cold_start is None:
        raise ValueError('The config needs the run and cold_start sections')
    c = config.cold_start
    config.run.clip_source = 'v1_file'  # v1's boundary
    boundary = load_clip_boundary(config)
    assert boundary is not None
    failed = False
    for model, m in config.traffic_models.items():
        year = model.removeprefix('visum')
        folder = Path(m.links).parent
        v1_links = gpd.read_file(folder / f'visum_links_{year}.gpkg')
        v1_zones = gpd.read_file(folder / f'visum_zones_{year}.gpkg')
        v1 = v1_starts(v1_links, v1_zones, c.vehicle_classes, c.road_types, c.buffer_m)

        config.run.traffic_model = model
        v2, report = load_link_starts(config)
        print(f'{model}: {report.zones} zones, {len(report.zones_without_links)} without an included link '
              f'in the buffer, lost daily starts {report.lost_starts}')
        for vc in c.vehicle_classes:
            a, b = v1[f'{vc}_cold_starts'].to_numpy(), v2[f'{vc}_starts'].to_numpy()
            ok = len(a) == len(b) and np.allclose(a, b, rtol=RTOL, atol=0)
            rel = np.max(np.abs(a - b) / np.maximum(np.abs(a), 1e-300)) if len(a) == len(b) else np.nan
            total_v1 = clipped_daily(v1, f'{vc}_cold_starts', boundary)
            total_v2 = clipped_daily(v2, f'{vc}_starts', boundary)
            ok &= bool(np.isclose(total_v1, total_v2, rtol=RTOL, atol=0))
            failed |= not ok
            print(f'  {vc}: {"identical" if ok else "DIFFERENT"} (max rel. diff {rel:.2g}); '
                  f'links with starts {(b > 0).sum()} of {len(b)}; daily starts {b.sum():.1f} '
                  f'(zones {v1_zones[f"{vc}_starts"].sum():.1f}), within the boundary v1 {total_v1:.1f} / v2 {total_v2:.1f}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml'))
