"""Counted vs modelled volumes and vehicle shares on the counted links of one scaling road type.

Usage: uv run python scripts/check_link_shares.py [configs/munich_2025.yaml] [scaling_road_type]

For each traffic model (with the series settings of scripts/run_series.py) and each counted link of the road
type: the mean of the normal weekdays of the reference year (IQR mean, as the counts QA uses for the SQV) per
vehicle class, against the model DTV of the link (both directions summed, as in the QA).

The kernel scales every link with one profile and one share per scaling road type, and re-introduces the spatial
differences of the HGV and LCV shares with hgv_corr = model share / mean counted share (lcv_corr alike). That is
right on a counted link when its model share is close to its counted share. Reported per link:
- SUM: counted / model and the SQV (validity, threshold from the config)
- HGV and LCV: counted share, model share, model / counted; the share the kernel gives the link on a normal
  weekday of the reference year (= model share) against the counted one
- the counted share relative to the road-type mean: the spatial difference the correction has to reproduce
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_series import SERIES, series_config

from drive import store
from drive.config import load_config
from drive.domain.counts_qa import iqr_mean, link_attributes
from drive.pipeline import load_link_counts

CLASSES = ['SUM', 'PC', 'LCV', 'HGV']


def link_table(config, road_type: str) -> pd.DataFrame:
    run, qa = config.run, config.counts_qa
    counts, _, version = load_link_counts(config)
    counts = counts[counts['scaling_road_type'] == road_type]
    reference = counts[(counts['date'].dt.year == run.reference_year) &
                       (counts['day_type'] == run.reference_day_type)]
    observed = reference.groupby(['road_link_id', 'vehicle_class'])['daily_value'] \
        .apply(iqr_mean, iqr_range=qa.iqr_range).unstack('vehicle_class')[CLASSES]
    days = reference[reference['vehicle_class'] == 'SUM'].groupby('road_link_id').size()
    flags = counts.groupby('road_link_id')[['valid', 'complete', 'road_type']].first()
    model = link_attributes(store.read_links(config.paths.store, run.traffic_model, version)).loc[observed.index]

    detectors = store.read_counter_links(config.paths.store, run.traffic_model, version)
    detectors = detectors[detectors['road_link_id'].isin(observed.index)] \
        .groupby('road_link_id')['detector_id'].agg(lambda d: ' '.join(sorted(d)))
    sources = store.read_counter_links(config.paths.store, run.traffic_model, version) \
        .groupby('road_link_id')['source'].first()

    t = pd.DataFrame(index=observed.index)
    t['source'] = sources.reindex(t.index)
    t['detectors'] = detectors.reindex(t.index)
    t['road_type'] = flags['road_type']
    t['valid'], t['complete'] = flags['valid'], flags['complete']
    t['days'] = days.reindex(t.index).fillna(0).astype(int)
    t['SUM_count'] = observed['SUM']
    t['SUM_model'] = model['dtv_SUM']
    t['SUM_ratio'] = t['SUM_count'] / t['SUM_model']
    for vc in ['HGV', 'LCV']:
        t[f'{vc}_count'] = observed[vc] / observed['SUM']
        t[f'{vc}_model'] = model[f'dtv_{vc}'] / model['dtv_SUM']
        t[f'{vc}_ratio'] = t[f'{vc}_model'] / t[f'{vc}_count']
    return t


def summary(t: pd.DataFrame, vc: str, tolerance: float = 0.25) -> str:
    """On a reference day the kernel gives a link share x corr = its model share, so model / counted is the
    error of the corrected share on that link."""
    used = t[t['valid'] & t['complete']].dropna(subset=[f'{vc}_count'])
    count, model, ratio = used[f'{vc}_count'], used[f'{vc}_model'], used[f'{vc}_ratio']
    outside = ratio[(ratio < 1 - tolerance) | (ratio > 1 + tolerance)]
    r = np.corrcoef(count, model)[0, 1] if len(used) > 2 else np.nan
    weighted = (used[f'{vc}_model'] * used['SUM_model']).sum() / (count * used['SUM_model']).sum()
    return (f'  {vc} on {len(used)} used links with a class split: counted share {count.mean():.3f} '
            f'({count.min():.3f}-{count.max():.3f}), model {model.mean():.3f} ({model.min():.3f}-{model.max():.3f}), '
            f'correlation {r:.2f}; model / counted median {ratio.median():.2f}, range {ratio.min():.2f}-{ratio.max():.2f}, '
            f'volume-weighted {weighted:.2f}; outside ±{tolerance:.0%}: {len(outside)} links '
            f'({", ".join(used.loc[outside.index, "detectors"])})')


def main(config_path: str = 'configs/munich_2025.yaml', road_type: str = 'Motorway-Nat') -> int:
    base = load_config(config_path)
    pd.set_option('display.width', 250)
    for model, settings in SERIES.items():
        config = series_config(base, settings['reference_year'])
        assert config.run.traffic_model == model
        t = link_table(config, road_type)
        used = t[t['valid'] & t['complete']]
        print(f'\n{model}, reference year {config.run.reference_year}, normal weekdays, {road_type}: '
              f'{len(t)} counted links, {len(used)} valid and complete (used for the profile and the shares)')
        show = t.copy()
        for c in ['SUM_count', 'SUM_model']:
            show[c] = show[c].round(0).astype('Int64')
        print(show.round(3).sort_values(['source', 'detectors']).to_string())
        print(f'  SUM counted / model on used links: {used["SUM_ratio"].min():.2f}-{used["SUM_ratio"].max():.2f}, '
              f'median {used["SUM_ratio"].median():.2f}; sum over used links {used["SUM_count"].sum() / used["SUM_model"].sum():.3f}')
        for vc in ['HGV', 'LCV']:
            print(summary(t, vc))
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
