"""
Configuración central del proyecto FIRMS Pipeline.
Carga settings.yaml y resuelve rutas relativas desde la raíz del proyecto.
"""

from __future__ import annotations

from pathlib import Path
from yaml_loader import load_settings

# Raíz del proyecto (un nivel arriba de src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Cargar settings.yaml
SETTINGS_FILE = PROJECT_ROOT / "config" / "settings.yaml"
if not SETTINGS_FILE.is_file():
    raise FileNotFoundError(f"No se encontró el archivo de configuración: {SETTINGS_FILE}")

_raw_settings = load_settings(SETTINGS_FILE)

# Rutas del proyecto resueltas desde la raíz
_paths = _raw_settings.get("paths", {})
DATASET_DIR = PROJECT_ROOT / "dataset"
MODIS_DIR = PROJECT_ROOT / _paths.get("modis", "dataset/modis")
SNPP_DIR = PROJECT_ROOT / _paths.get("snpp", "dataset/snpp")
NOAA20_DIR = PROJECT_ROOT / _paths.get("noaa20", "dataset/noaa20")
NOAA21_DIR = PROJECT_ROOT / _paths.get("noaa21", "dataset/noaa21")

REPORTS_DIR = PROJECT_ROOT / _paths.get("reports", "output/reports")
INTERIM_DIR = PROJECT_ROOT / _paths.get("interim", "output/interim")
PROCESSED_DIR = PROJECT_ROOT / _paths.get("processed", "output/processed")
WEB_DIR = PROJECT_ROOT / _paths.get("web", "output/web")

# Por compatibilidad con firmas
DEFAULT_OUT_DIR = REPORTS_DIR

# Rango de años y ventanas
_years = _raw_settings.get("years", {})
YEAR_MIN = _years.get("min", 2012)
YEAR_MAX = _years.get("max", 2017)

WINDOWS = {
    "calibration": [2012, 2017],
    "validation": [2018, 2022],
    "final": [2012, 2022],
    **_raw_settings.get("windows", {}),
}

# Procesamiento
_proc = _raw_settings.get("processing", {})
UTC_OFFSET_HOURS = _proc.get("utc_offset_hours", -5)
CELL_SIZE = _proc.get("cell_size_deg", 0.25)
# Malla única de resolución variable: celda de 0.1° (~11 km) desde 2012 y de 0.25° antes (cleaning.CELL_COLS)
FINE_CELL_SIZE = float(_proc.get("fine_cell_size_deg", 0.1))
FINE_CELL_FROM_YEAR = int(_proc.get("fine_cell_from_year", 2012))

# Temporadas: nombre -> meses (mes del jueves de la semana ISO)
SEASONS = _raw_settings.get("seasons", {
    "alta": [8, 9],
    "media": [6, 7, 10, 11],
    "baja": [12, 1, 2, 3, 4, 5],
})

# Apagones documentados: sensor -> (inicio, fin) inclusivos, como texto AAAA-MM-DD
OUTAGES = {
    sensor: (str(span[0]), str(span[-1]))
    for sensor, span in (_raw_settings.get("outages") or {}).items()
}

# Armonización (serie única). Los períodos se escriben como lista plana de pares inicio, fin.
_harm = _raw_settings.get("harmonize") or {}
_gaps = [str(x) for x in (_harm.get("aqua_gaps") or [])]
if len(_gaps) % 2:
    raise ValueError("settings.yaml -> harmonize.aqua_gaps debe tener pares inicio, fin")
HARMONIZE = {
    "estimated": [int(y) for y in _harm.get("estimated", [2002, 2011])],
    "aqua_start": str(_harm.get("aqua_start", "2002-07-04")),
    "aqua_gaps": [(_gaps[i], _gaps[i + 1]) for i in range(0, len(_gaps), 2)],
    "band_coverage": float(_harm.get("band_coverage", 0.90)),
}

# Climatología: línea base y áreas de interés (rectángulos lat_min, lat_max, lon_min, lon_max)
_clim = _raw_settings.get("climatology") or {}
CLIMATOLOGY = {
    "baseline": [int(y) for y in _clim.get("baseline", [2003, 2024])],
    "aois": {k[len("aoi_"):]: [float(v) for v in vals] for k, vals in _clim.items() if k.startswith("aoi_")},
}

# Máscara de fuentes estáticas (decisión 12)
STATIC_MASK = {
    "enabled": True,
    "cell_deg": 0.01,
    "buffer_cells": 1,
    "min_years": 2,
    **(_raw_settings.get("static_mask") or {}),
}

# Bounding Box Perú
PERU_BBOX = _raw_settings.get("bbox", dict(lat_min=-18.5, lat_max=0.1, lon_min=-81.5, lon_max=-68.5))

# Alertas
_alerts = _raw_settings.get("alerts", {})
MAX_GAP_DAYS = _alerts.get("max_gap_days", 3)
MAX_LOW_CONF_PCT = float(_alerts.get("max_low_conf_pct", 40.0))
MAX_PASS_SHIFT_MIN = _alerts.get("max_pass_shift_min", 60)
MAX_YOY_RATIO_CHANGE = float(_alerts.get("max_yoy_ratio_change", 0.30))

# Sensores opcionales
OPTIONAL_SOURCES = {"noaa20", "noaa21"}
REQUIRED = ["latitude", "longitude", "acq_date", "acq_time", "frp", "confidence"]

# fuente -> familia, sensor fijo (None = se lee de 'satellite') y prefijo del nombre de archivo
SOURCES = {
    "modis":  dict(family="MODIS", sensor=None,     prefix="modis"),
    "snpp":   dict(family="VIIRS", sensor="SNPP",   prefix="viirs-snpp"),
    "noaa20": dict(family="VIIRS", sensor="NOAA20", prefix="viirs-(?:jpss1|noaa20)"),
    "noaa21": dict(family="VIIRS", sensor="NOAA21", prefix="viirs-(?:jpss2|noaa21)"),
}
