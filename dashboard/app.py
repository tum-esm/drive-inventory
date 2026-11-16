"""DRIVE dashboard (spec R27, D33): local Streamlit app, read-only on the store and the run outputs.

Start: `uv run --group dashboard drive dashboard configs/munich_2025.yaml`
   or: `uv run --group dashboard streamlit run dashboard/app.py -- configs/munich_2025.yaml`
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import dashboard_data as data

from drive.config import load_config
from drive.domain.calendar import DAY_GROUPS
from drive.schemas import HOURS

st.set_page_config(page_title='DRIVE dashboard', layout='wide')
CONFIG_PATH = sys.argv[1] if len(sys.argv) > 1 else 'configs/munich_2025.yaml'
REFERENCE_YEARS = {'visum2019': 2019, 'visum2025': 2025}  # the series settings (scripts/run_series.py, D31)
MUNICH = pdk.ViewState(latitude=48.137, longitude=11.575, zoom=10.3)


@st.cache_resource
def config():
    return load_config(CONFIG_PATH)


@st.cache_data(show_spinner='Reading the traffic model ...')
def links_layer_data(traffic_model: str) -> pd.DataFrame:
    links = data.model_links(config(), traffic_model)
    # widths in metres (pydeck turns the string 'pixels' into a JS expression, so no width_units), limited in pixels
    width = 5 + 70 * np.sqrt(links['dtv_SUM'].clip(lower=0) / links['dtv_SUM'].max())
    return pd.DataFrame({'path': data.to_wgs84_paths(links),
                         'road_type': links['road_type'],
                         'dtv_SUM': links['dtv_SUM'].round(0),
                         'width': width,
                         'colour': links['road_type'].map(lambda r: data.ROAD_TYPE_COLOURS.get(r, [120, 120, 120]))})


@st.cache_data(show_spinner='Reading the counters ...')
def counter_layer_data(traffic_model: str) -> pd.DataFrame:
    points = data.counters(config(), traffic_model).to_crs(4326)
    colours = {'BASt': [20, 20, 20], 'LHM': [130, 40, 160]}
    return pd.DataFrame({'lon': points.geometry.x, 'lat': points.geometry.y, 'source': points['source'],
                         'detector_id': points['detector_id'], 'road_link_id': points['road_link_id'],
                         'colour': points['source'].map(colours)})


@st.cache_resource(show_spinner='Computing the activity of the traffic model (counts QA and scaling) ...')
def model_activity(traffic_model: str):
    return data.activity(config(), traffic_model, REFERENCE_YEARS[traffic_model])


@st.cache_data
def runs() -> list[data.Run]:
    return data.find_runs(config().paths.results / 'series')


@st.cache_data(show_spinner='Reading the line sources ...')
def line_layer_data(stem: str, kind: str, component: str) -> pd.DataFrame:
    run = next(r for r in runs() if r.stem == stem)
    frame = data.line_sources(run, kind, component)
    value = frame['value'].to_numpy()
    scale = np.sqrt(np.clip(value, 0, None) / max(np.nanpercentile(value, 99), 1e-12))
    return pd.DataFrame({'path': data.to_wgs84_paths(frame), 'road_type': frame['road_type'],
                         'value': value.round(1), 'width': 5 + 50 * np.clip(scale, 0, 1.5),
                         'colour': data.colour_scale(value).tolist()})


@st.cache_data(show_spinner='Reading the grid ...')
def grid_layer_data(stem: str, grid_name: str, kind: str, component: str) -> pd.DataFrame:
    run = next(r for r in runs() if r.stem == stem)
    frame = data.grid(run, grid_name, kind, component).to_crs(4326)
    polygons = [[[x, y] for x, y, *_ in geometry.exterior.coords] for geometry in frame.geometry]
    return pd.DataFrame({'polygon': polygons, 'value': frame['value'].round(2),
                         'colour': data.colour_scale(frame['value'].to_numpy()).tolist()})


BAR_WIDTH, BAR_HEIGHT = 900, 450  # pixels, so that year-to-year differences stay visible on wide screens


def tonnes(value: float, scale: float) -> str:
    """Tonnes in t, kt or Mt depending on the scale of the chart."""
    if scale >= 1e6:
        return f'{value / 1e6:.2f} Mt'
    if scale >= 1e3:
        return f'{value / 1e3:.1f} kt'
    return f'{value:.1f} t'


def with_totals(figure, totals: pd.DataFrame, x: str, y: str, labels: list[str], lowest: float = 0.0):
    """Writes the total of each stacked bar above it.

    Args:
        lowest: the lowest stacked value (sum of the negative parts, e.g. cold excess NOx), so it stays visible
    """
    figure.add_trace(go.Scatter(x=totals[x], y=totals[y], text=labels, mode='text', textposition='top center',
                                showlegend=False, hoverinfo='skip', cliponaxis=False))
    top = max(totals[y].max(), 0.0)
    figure.update_yaxes(range=[min(lowest * 1.1, 0.0), top * 1.12 if top > 0 else 1.0])
    return figure


def deck(layers: list, tooltip: dict) -> pdk.Deck:
    return pdk.Deck(layers=layers, initial_view_state=MUNICH, map_provider='carto', map_style='light',
                    tooltip=tooltip)


st.title('DRIVE dashboard')
st.caption(f'Config `{CONFIG_PATH}` · store `{config().paths.store.name}` · results `{config().paths.results}/series`')
tabs = st.tabs(['Input map', 'Scaling', 'Vehicle-km', 'Emission map', 'Emission totals'])

# ---- (1) input map: traffic model and counters ----
with tabs[0]:
    left, right = st.columns([1, 3])
    model = left.selectbox('Traffic model', list(REFERENCE_YEARS), index=1, key='map_model')
    road_types = left.multiselect('Road types', list(data.ROAD_TYPE_COLOURS), default=list(data.ROAD_TYPE_COLOURS))
    show_counters = left.checkbox('Show counters', value=True)
    for road_type, colour in data.ROAD_TYPE_COLOURS.items():
        left.markdown(f"<span style='color:rgb{tuple(colour)}'>━━</span> {road_type}", unsafe_allow_html=True)
    left.caption('Line width: total daily volume of both directions (dtv_SUM). Counters: black BASt, purple LHM, '
                 'at the midpoint of their matched link.')
    links = links_layer_data(model)
    layers = [pdk.Layer('PathLayer', links[links['road_type'].isin(road_types)], get_path='path',
                        get_color='colour', get_width='width', width_min_pixels=1, width_max_pixels=12,
                        pickable=True)]
    if show_counters:
        layers.append(pdk.Layer('ScatterplotLayer', counter_layer_data(model), get_position='[lon, lat]',
                                get_fill_color='colour', get_radius=60, radius_min_pixels=4, radius_max_pixels=10,
                                pickable=True,
                                stroked=True, get_line_color=[255, 255, 255]))
    right.pydeck_chart(deck(layers, {'text': '{road_type} {dtv_SUM} veh/day\n{source} {detector_id} link {road_link_id}'}),
                       height=700, alt=f'Road network of {model} by road type with the counting stations')

# ---- (2) scaling: annual profile and diurnal cycles ----
with tabs[1]:
    model = st.selectbox('Traffic model (reference year)', list(REFERENCE_YEARS), index=1, key='scaling_model',
                         format_func=lambda m: f'{m} ({REFERENCE_YEARS[m]})')
    act, report = model_activity(model)
    cycles = act.annual_cycles.rename('scaling').reset_index()
    road_types = st.multiselect('Scaling road types', sorted(cycles['scaling_road_type'].unique()),
                                default=sorted(cycles['scaling_road_type'].unique()))
    first, last = cycles['date'].min().date(), cycles['date'].max().date()
    span = st.slider('Time span', min_value=first, max_value=last, value=(first, last), format='YYYY-MM-DD')
    shown = cycles[cycles['scaling_road_type'].isin(road_types) & cycles['date'].dt.date.between(*span)]
    figure = px.line(shown, x='date', y='scaling', color='scaling_road_type',
                     labels={'scaling': 'daily scaling (1 = normal weekday of the reference year)', 'date': ''})
    st.plotly_chart(figure, width='stretch', alt='Daily scaling per scaling road type over time')
    st.caption(f'Usable counters per year (valid and complete, D29): {report.usable_links}')

    st.subheader('Diurnal cycles')
    daily = act.daily_cycles.reset_index()
    columns = st.columns(4)
    year = columns[0].selectbox('Year', sorted(daily['year'].unique()), index=len(daily['year'].unique()) - 1)
    month = columns[1].selectbox('Month', list(range(1, 13)), index=5, format_func=lambda m: f'{m:02d}')
    groups = sorted(set(DAY_GROUPS.values()))
    day_group = columns[2].selectbox('Day type', groups, format_func=lambda g: data.DAY_GROUP_NAMES.get(g, str(g)))
    classes = columns[3].multiselect('Vehicle classes', ['PC', 'LCV', 'HGV', 'BUS', 'MOT', 'SUM'],
                                     default=['PC', 'LCV', 'HGV'])
    sel = daily[(daily['year'] == year) & (daily['month'] == month) & (daily['day_type'] == day_group)
                & daily['vehicle_class'].isin(classes)]
    long = sel.melt(id_vars=['vehicle_class'], value_vars=HOURS, var_name='hour', value_name='share')
    long['hour'] = long['hour'].str[1:].astype(int)
    figure = px.line(long, x='hour', y='share', color='vehicle_class', markers=True,
                     labels={'share': 'share of the daily volume', 'hour': 'hour (local time)'})
    st.plotly_chart(figure, width='stretch', alt='Diurnal cycles per vehicle class for the selected year, month and day type')

# ---- (3) vehicle-km and level-of-service shares ----
with tabs[2]:
    vkt = data.vehicle_km(runs())
    if vkt.empty:
        st.info('No vkt_*.csv in the series folder yet; run scripts/run_series.py.')
    else:
        per_class = vkt.groupby(['run', 'year', 'vehicle_class'], as_index=False)['vkt_km'].sum()
        per_class['billion vehicle-km'] = per_class['vkt_km'] / 1e9
        figure = px.bar(per_class.sort_values('year'), x='run', y='billion vehicle-km', color='vehicle_class',
                        title='Vehicle-km per year and vehicle class', labels={'run': ''})
        total = per_class.groupby('run', as_index=False)['billion vehicle-km'].sum()
        with_totals(figure, total, 'run', 'billion vehicle-km', [f'{v:.2f}' for v in total['billion vehicle-km']])
        st.plotly_chart(figure, width=BAR_WIDTH, height=BAR_HEIGHT, alt='Vehicle-km per year and vehicle class')
        los = vkt.groupby(['run', 'year', 'level_of_service'], as_index=False)['vkt_km'].sum()
        los['share'] = los['vkt_km'] / los.groupby('run')['vkt_km'].transform('sum') * 100
        order = ['Freeflow', 'Heavy', 'Satur.', 'St+Go', 'St+Go2']
        figure = px.bar(los.sort_values('year'), x='run', y='share', color='level_of_service',
                        category_orders={'level_of_service': order}, title='Level-of-service share of vehicle-km',
                        labels={'share': '% of vehicle-km', 'run': ''}, text_auto='.0f')
        # labels only where they fit; thin segments (St+Go2, about 1 %) would overlap
        figure.update_traces(textposition='inside', insidetextanchor='middle')
        figure.update_layout(uniformtext_minsize=10, uniformtext_mode='hide')
        st.plotly_chart(figure, width=BAR_WIDTH, height=BAR_HEIGHT, alt='Level-of-service share of vehicle-km per year')

# ---- (4) emission map ----
with tabs[3]:
    available = runs()
    if not available:
        st.info('No runs in the series folder yet; run scripts/run_series.py.')
    else:
        left, right = st.columns([1, 3])
        run = left.selectbox('Run', available, index=len(available) - 1, format_func=lambda r: r.label)
        components = sorted(pd.read_csv(run.folder / f'summary_{run.stem}.csv')['component'].unique())
        component = left.selectbox('Component', components, index=components.index('NOx') if 'NOx' in components else 0)
        kind = left.segmented_control('Emissions', ['hot', 'cold', 'total'], default='hot', required=True)
        view = left.segmented_control('Display', ['Line sources', 'Grid'], default='Line sources', required=True)
        if view == 'Grid':
            names = data.grid_names(run)
            grid_name = left.selectbox('Grid', names) if names else None
            if grid_name is None:
                left.warning('No grid files for this run.')
            else:
                cells = grid_layer_data(run.stem, grid_name, kind, component)
                layer = pdk.Layer('PolygonLayer', cells[cells['value'] > 0], get_polygon='polygon',
                                  get_fill_color='colour', stroked=False, pickable=True)
                right.pydeck_chart(deck([layer], {'text': f'{component} {{value}} kg/year'}), height=700,
                                   alt=f'{kind} {component} emissions per {grid_name} grid cell, {run.label}')
                left.caption(f'Total {cells["value"].sum() / 1000:,.1f} t; colour on a log scale.')
        else:
            lines = line_layer_data(run.stem, kind, component)
            layer = pdk.Layer('PathLayer', lines[lines['value'] > 0], get_path='path', get_color='colour',
                              get_width='width', width_min_pixels=1, width_max_pixels=10, pickable=True)
            right.pydeck_chart(deck([layer], {'text': f'{{road_type}}\n{component} {{value}} g/km/year'}), height=700,
                               alt=f'{kind} {component} emissions per road link, {run.label}')
            left.caption('Colour (log scale) and width: g/km over the year, summed over the vehicle classes. '
                         'Cold starts only on access, local and distributor roads.')

# ---- (5) emission totals across years ----
with tabs[4]:
    summary = data.summaries(runs())
    if summary.empty:
        st.info('No runs in the series folder yet; run scripts/run_series.py.')
    else:
        columns = st.columns(3)
        components = sorted(summary['component'].unique())
        component = columns[0].selectbox('Component', components,
                                         index=components.index('CO2(rep)') if 'CO2(rep)' in components else 0)
        split = columns[1].segmented_control('Bars split by', ['hot / cold', 'vehicle class', 'road type'],
                                         default='hot / cold', required=True)
        models = columns[2].multiselect('Traffic models', sorted(summary['model'].unique()),
                                        default=sorted(summary['model'].unique()))
        sel = summary[(summary['component'] == component) & summary['model'].isin(models)]
        colour = {'hot / cold': 'kind', 'vehicle class': 'vehicle_class', 'road type': 'road_type'}[split]
        totals = sel.groupby(['run', 'year', colour], as_index=False)['emission_t'].sum().sort_values('year')
        figure = px.bar(totals, x='run', y='emission_t', color=colour,
                        title=f'{component}: total emissions per year (t)', labels={'emission_t': 't', 'run': ''})
        total = totals.groupby('run', as_index=False, sort=False)['emission_t'].sum()
        scale = total['emission_t'].abs().max()
        negative = totals[totals['emission_t'] < 0].groupby('run')['emission_t'].sum()
        with_totals(figure, total, 'run', 'emission_t', [tonnes(v, scale) for v in total['emission_t']],
                    lowest=float(negative.min()) if len(negative) else 0.0)
        st.plotly_chart(figure, width=BAR_WIDTH, height=BAR_HEIGHT,
                        alt='Total emissions of the selected component per year')
        table = sel.pivot_table(index='run', columns='kind', values='emission_t', aggfunc='sum')
        table['total'] = table.sum(axis=1)
        st.dataframe(table.round(1), width='stretch')
