"""Adapter for raw VISUM exports (link and zone shapefiles), port of v1 preprocessing 21 and 21v2.

Steps for links: map column names, parse number fields, drop links below the minimum traffic,
assign HBEFA road types and drop excluded types, snap gradient and speed to the values in
HBEFA, sum HGV, and map the scaling road type.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely

from drive.config import VisumConfig
from drive.schemas import HBEFA_SPEEDS, LINKS, ZONES

_LINK_FIELDS = ['NO', 'FROMNODENO', 'TONODENO', 'TYPENO', 'NUMLANES', 'CAPPRT', 'V0PRT', 'LENGTH', 'SLOPE',
                'SUMME_KFZ', 'BEL_PKW', 'BEL_LKW_K', 'BEL_LKW_M', 'BEL_LKW_G']
_HBEFA_GRADIENTS = np.array([-6, -4, -2, 0, 2, 4, 6])


@dataclass
class LinksReport:
    raw_rows: int
    below_min_dtv: int
    excluded_typeno: int  # rows above min_dtv in excluded TYPENO ranges
    excluded_typeno_dtv: float
    rows: int
    road_link_ids: int
    road_type_ambiguous: list[int]  # ids whose directions disagree on the road type


def _read_raw(path: str | Path, crs: str, geometry_type: str) -> pd.DataFrame:
    frame = pyogrio.read_dataframe(path)
    if frame.crs is None or frame.crs != crs:
        raise ValueError(f'{path} has CRS {frame.crs}, expected {crs}')
    wrong = frame.geometry.isna() | frame.geometry.is_empty | (frame.geometry.geom_type != geometry_type)
    if wrong.any():
        raise ValueError(f'{path} has {wrong.sum()} rows that are empty or not a {geometry_type}')
    frame['file_row'] = range(len(frame))
    return frame


def _number(values: pd.Series, unit: str) -> pd.Series:
    """Numbers from a numeric field, or from text with a unit and a decimal comma (`0,242km`)."""
    if pd.api.types.is_numeric_dtype(values):
        return values.astype(float)
    text = values.astype(str).str.removesuffix(unit).str.replace(',', '.')
    return pd.to_numeric(text, errors='raise')


def road_types(typeno: pd.Series, speed: pd.Series, config: VisumConfig) -> pd.Series:
    """HBEFA road type per link, NaN for excluded TYPENO ranges.

    Raises:
        ValueError: for a TYPENO that no rule and no excluded range covers
    """
    result = pd.Series(np.nan, index=typeno.index, dtype=object)
    for rule in config.road_types:
        match = typeno.between(*rule.typeno) & result.isna()
        if rule.min_speed is not None:
            match &= speed >= rule.min_speed
        result[match] = rule.road_type  # pyright: ignore[reportCallIssue, reportArgumentType]  # object Series, stubs expect float
    excluded = np.logical_or.reduce([typeno.between(*r) for r in config.excluded_typeno])
    unknown = result.isna() & ~excluded
    if unknown.any():
        raise ValueError(f'No road type rule for TYPENO {sorted(typeno[unknown].unique().tolist())}')
    return result


def hbefa_gradients(slope: pd.Series) -> pd.Series:
    """Nearest HBEFA gradient as text (`-2%`, `0%`, `+2%`). Ties go to the lower gradient, as in v1."""
    nearest = _HBEFA_GRADIENTS[np.abs(slope.to_numpy()[:, None] - _HBEFA_GRADIENTS).argmin(axis=1)]
    return pd.Series([f'{g:+d}%' if g != 0 else '0%' for g in nearest], index=slope.index)


def hbefa_speeds(road_type: pd.Series, speed: pd.Series) -> pd.Series:
    """Nearest speed with an HBEFA traffic situation on that road type. Ties go to the lower speed, as in v1."""
    result = pd.Series(0, index=speed.index, dtype='int64')
    for name, group in speed.groupby(road_type):
        options = np.array(HBEFA_SPEEDS[name])
        result[group.index] = options[np.abs(group.to_numpy()[:, None] - options).argmin(axis=1)]
    return result


def read_links(path: str | Path,
               traffic_model: str,
               crs: str,
               column_names: dict[str, str],
               config: VisumConfig,
               scaling_road_types: dict[str, str]) -> tuple[pd.DataFrame, LinksReport]:
    """Reads a raw link export into the LINKS contract.

    Args:
        column_names: raw name -> standard VISUM name, for exports with other names
        config: conversion rules
        scaling_road_types: road type -> scaling road type, unlisted types map to themselves

    Raises:
        ValueError: on a CRS mismatch, unexpected geometries, an unknown TYPENO or a contract violation
    """
    raw = _read_raw(path, crs, 'LineString').rename(columns=column_names)
    missing = sorted(set(_LINK_FIELDS) - set(raw.columns))
    if missing:
        raise ValueError(f'{path} lacks the fields {missing}, set link_columns for this model')

    raw['speed'] = _number(raw['V0PRT'], 'km/h').astype('int64')
    raw['length'] = _number(raw['LENGTH'], 'km')
    raw['typeno'] = raw['TYPENO'].astype('int64')

    kept = raw[raw['SUMME_KFZ'] >= config.min_dtv].copy()
    kept['road_type'] = road_types(kept['typeno'], kept['speed'], config)
    excluded = kept['road_type'].isna()
    report_excluded, report_excluded_dtv = int(excluded.sum()), float(kept.loc[excluded, 'SUMME_KFZ'].sum())
    kept = kept[~excluded]

    links = pd.DataFrame({
        'traffic_model': traffic_model,
        'road_link_id': kept['NO'],
        'from_node': kept['FROMNODENO'],
        'to_node': kept['TONODENO'],
        'file_row': kept['file_row'],
        'typeno': kept['typeno'],
        'road_type': kept['road_type'].astype(str),
        'scaling_road_type': kept['road_type'].map(lambda t: scaling_road_types.get(str(t), t)),
        'hour_capacity': kept['CAPPRT'],
        'lanes': kept['NUMLANES'],
        'hbefa_speed': hbefa_speeds(kept['road_type'], kept['speed']),
        'speed': kept['speed'],
        'hbefa_gradient': hbefa_gradients(kept['SLOPE']),
        'dtv_SUM': kept['SUMME_KFZ'].astype(float),
        'dtv_PC': kept['BEL_PKW'].astype(float),
        'dtv_LCV': kept['BEL_LKW_K'].astype(float),
        'dtv_HGV': (kept['BEL_LKW_M'] + kept['BEL_LKW_G']).astype(float),
        'visum_length_km': kept['length'],
        'crs': crs,
        'geometry': shapely.to_wkb(np.asarray(kept.geometry)),
    }).reset_index(drop=True)
    links = LINKS.validate(links)

    ambiguous = links.groupby('road_link_id')['road_type'].nunique()
    return links, LinksReport(raw_rows=len(raw),
                              below_min_dtv=len(raw) - report_excluded - len(links),
                              excluded_typeno=report_excluded,
                              excluded_typeno_dtv=report_excluded_dtv,
                              rows=len(links),
                              road_link_ids=links['road_link_id'].nunique(),
                              road_type_ambiguous=sorted(ambiguous.index[ambiguous > 1].tolist()))


def read_zones(path: str | Path, traffic_model: str, crs: str, column_names: Mapping[str, str]) -> pd.DataFrame:
    """Reads a raw zone export into the ZONES contract. Starts a model doesn't map stay NaN (HGV).

    Raises:
        ValueError: on a CRS mismatch, unexpected geometries or a contract violation
    """
    raw = _read_raw(path, crs, 'Polygon').rename(columns=column_names)
    missing = sorted({'NO', 'PC_starts', 'LCV_starts'} - set(raw.columns))
    if missing:
        raise ValueError(f'{path} lacks the fields {missing}, set zone_columns for this model')
    zones = pd.DataFrame({
        'traffic_model': traffic_model,
        'zone_id': raw['NO'],
        'file_row': raw['file_row'],
        'PC_starts': raw['PC_starts'],
        'LCV_starts': raw['LCV_starts'],
        'HGV_starts': raw['HGV_starts'] if 'HGV_starts' in raw else float('nan'),
        'crs': crs,
        'geometry': shapely.to_wkb(np.asarray(raw.geometry)),
    })
    return ZONES.validate(zones)
