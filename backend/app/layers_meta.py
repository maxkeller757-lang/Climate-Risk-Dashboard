"""
Static display metadata for the 9 map layers (8 hazard categories +
composite). This is display config, not computed data -- scores themselves
always come from the pre-computed pipeline output, never from here.
"""

LAYERS = [
    {
        "category": "severe_convective",
        "name": "Severe Convective",
        "description": "Tornado, hail, and thunderstorm wind exposure (NCEI Storm Events, 2015-2024).",
        "color": "#7B2D8E",
    },
    {
        "category": "flood",
        "name": "Flood",
        "description": "Share of ZCTA area inside a FEMA Special Flood Hazard Area (Zone A/AE/V/VE).",
        "color": "#1E88A8",
    },
    {
        "category": "wildfire",
        "name": "Wildfire",
        "description": "USFS Wildfire Hazard Potential plus historical burn perimeters, 2015-2024.",
        "color": "#D32F2F",
    },
    {
        "category": "hurricane",
        "name": "Hurricane / Tropical",
        "description": "Wind-speed-weighted exposure from NOAA HURDAT2 track proximity, 2015-2024.",
        "color": "#00707A",
    },
    {
        "category": "winter_weather",
        "name": "Winter Weather",
        "description": "Winter storm, ice storm, heavy snow, and blizzard exposure (NCEI Storm Events, 2015-2024).",
        "color": "#6EC6E8",
    },
    {
        "category": "drought",
        "name": "Drought",
        "description": "Average share of time in D0-D4 drought, U.S. Drought Monitor, 2015-2024.",
        "color": "#B8860B",
    },
    {
        "category": "heat",
        "name": "Extreme Heat",
        "description": "Blend of days/year above 90F and days/year with NWS heat index above 100F.",
        "color": "#E85D04",
    },
    {
        "category": "seismic",
        "name": "Seismic",
        "description": "USGS National Seismic Hazard Model (PGA) blended with volcanic threat near active systems.",
        "color": "#8B5E3C",
    },
    {
        "category": "air_quality",
        "name": "Air Quality",
        "description": "Average days per year with PM2.5 above the AQI 100 threshold (CDC/EPA fused daily surface, 2015-2021).",
        "color": "#9A9A94",
    },
    {
        "category": "composite",
        "name": "Composite",
        "description": "Weighted power-mean of all 8 category scores -- compounding hazards score higher than a plain average would (see composite_weights.json).",
        "color_ramp": ["#2E7D32", "#F9A825", "#C62828"],
    },
]

LAYERS_BY_CATEGORY = {layer["category"]: layer for layer in LAYERS}
