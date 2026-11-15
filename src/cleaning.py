"""
Módulo de limpieza, estandarización y filtrado de datos FIRMS.
Funciones puras de transformación sobre DataFrames sin acceso directo a disco.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import CELL_SIZE, FINE_CELL_FROM_YEAR, FINE_CELL_SIZE, UTC_OFFSET_HOURS

# Columnas espaciales de las tablas por celda (malla única de resolución variable):
#   cell, lat_c, lon_c        celda del mapa: 0.25° antes de FINE_CELL_FROM_YEAR y 0.1° desde ese año
#   cell_deg                  tamaño de esa celda en grados (0.25 o 0.1): diferencia las dos épocas
#   cell_025, lat_025, lon_025 celda de análisis de 0.25° (todos los años). Las áreas (Cusco) y la
#                             climatología se suman con ella, para que 2002-2011 y 2012+ tengan los mismos bordes.
# Una celda de 0.1° que cruza el borde de una de 0.25° se parte en dos filas (una por celda de 0.25°), así
# que sumar por cell da el total exacto de la celda del mapa y sumar por cell_025, el de la celda de análisis.
CELL_COLS = ["cell", "lat_c", "lon_c", "cell_deg", "cell_025", "lat_025", "lon_025"]


def confidence_to_category(series: pd.Series, is_modis: bool) -> pd.Series:
    """MODIS: 0-100 numérico. VIIRS: l / n / h. Devuelve low / medium / high."""
    numeric = pd.to_numeric(series, errors="coerce")
    if is_modis or numeric.notna().mean() > 0.9:
        cat = pd.cut(numeric, bins=[-1, 29, 79, 100], labels=["low", "medium", "high"])
        return cat.astype("object")
    mapping = {
        "l": "low", "low": "low",
        "n": "medium", "nominal": "medium",
        "h": "high", "high": "high",
    }
    return series.astype(str).str.strip().str.lower().map(mapping)


def assign_modis_sensor(df: pd.DataFrame) -> pd.Series:
    """Asigna el sensor Aqua o Terra a partir de la columna 'satellite' de MODIS."""
    if "satellite" not in df.columns:
        return pd.Series("MODIS_desconocido", index=df.index)
    sat = df["satellite"].astype(str).str.strip().str.lower()
    out = pd.Series("MODIS_desconocido", index=df.index)
    out[sat.isin(["aqua", "a"])] = "Aqua"
    out[sat.isin(["terra", "t"])] = "Terra"
    return out


def standardize(df: pd.DataFrame, info: dict, stats: dict) -> pd.DataFrame:
    """
    Estandariza tipos, calcula hora local, deduplica, categoriza confianza y asigna celda espacial.
    Actualiza el diccionario stats in-place con conteos de registros crudos, horas inválidas y duplicados.
    """
    df["family"] = info["family"]
    df["sensor"] = assign_modis_sensor(df) if info["sensor"] is None else info["sensor"]

    for col in ["latitude", "longitude", "frp"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Fecha/hora UTC -> hora local de Perú
    acq_time = pd.to_numeric(df["acq_time"], errors="coerce").fillna(-1).astype(int)
    hhmm = acq_time.astype(str).str.zfill(4)
    date_txt = df["acq_date"].astype(str).str.slice(0, 10)
    utc = pd.to_datetime(date_txt + " " + hhmm, format="%Y-%m-%d %H%M", errors="coerce")
    stats["invalid_time"] = int(utc.isna().sum())
    df = df[utc.notna()].copy()
    utc = utc[utc.notna()]

    local = utc + pd.Timedelta(hours=UTC_OFFSET_HOURS)
    df["acq_day"] = utc.dt.floor("D")            # fecha UTC (la del archivo)
    df["local_date"] = local.dt.floor("D")       # fecha local (UTC-5)
    df["local_minutes"] = local.dt.hour * 60 + local.dt.minute

    # Duplicados
    before = len(df)
    df = df.drop_duplicates(subset=["latitude", "longitude", "acq_date", "acq_time", "sensor"])
    stats["duplicates"] = before - len(df)

    # Tipo de fuente: 0 = vegetación. Si no existe la columna, se asume todo válido.
    if "type" in df.columns:
        df["type_num"] = pd.to_numeric(df["type"], errors="coerce")
    else:
        df["type_num"] = np.nan
    df["is_veg"] = df["type_num"].fillna(0).eq(0)

    # Producto: Near Real-Time (version "2.0NRT", "6.1NRT", ...) vs estándar. El NRT es preliminar:
    # FIRMS lo reemplaza por el estándar con meses de retraso.
    if "version" in df.columns:
        df["is_nrt"] = df["version"].astype(str).str.upper().str.contains("NRT", regex=False)
    else:
        df["is_nrt"] = False

    # Confianza
    df["confidence_cat"] = confidence_to_category(df["confidence"], info["family"] == "MODIS")
    df["is_low"] = df["confidence_cat"].eq("low")

    # Celdas (se guarda el CENTRO). Ver CELL_COLS.
    df["lat_025"], df["lon_025"], df["cell_025"] = assign_cell(df["latitude"], df["longitude"], CELL_SIZE)
    lat_f, lon_f, cell_f = assign_cell(df["latitude"], df["longitude"], FINE_CELL_SIZE)
    fine = df["local_date"].dt.year >= FINE_CELL_FROM_YEAR
    df["cell_deg"] = np.where(fine, FINE_CELL_SIZE, CELL_SIZE)
    df["lat_c"] = lat_f.where(fine, df["lat_025"])
    df["lon_c"] = lon_f.where(fine, df["lon_025"])
    df["cell"] = cell_f.where(fine, df["cell_025"])
    return df


def assign_cell(lat: pd.Series, lon: pd.Series, size: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Centro (lat_c, lon_c) e id "{lat_c:.3f}_{lon_c:.3f}" de la celda de `size` grados de cada punto."""
    lat_c = ((np.floor(lat / size) + 0.5) * size).round(4)
    lon_c = ((np.floor(lon / size) + 0.5) * size).round(4)
    return lat_c, lon_c, lat_c.map("{:.3f}".format) + "_" + lon_c.map("{:.3f}".format)


# --- Máscara de fuentes estáticas (decisión 12) ---------------------------------------------
# MODIS solo tipifica bien las fuentes estáticas desde la versión 03 (2018). Antes, las mismas
# ubicaciones salen como type=0. La máscara junta las ubicaciones marcadas type 1/2 por cualquier
# sensor en cualquier año y las excluye de todos los años, para que todo el período use el mismo criterio.

_KEY_BASE = 1_000_000  # codifica (i, j) en un entero: i * _KEY_BASE + j (|j| < _KEY_BASE)


def _grid_keys(lat: pd.Series, lon: pd.Series, cell_deg: float) -> pd.Series:
    """Índice entero de la celda de la máscara para cada punto."""
    i = np.floor(lat.to_numpy() / cell_deg).astype("int64")
    j = np.floor(lon.to_numpy() / cell_deg).astype("int64")
    return pd.Series(i * _KEY_BASE + j, index=lat.index)


def build_static_mask(points: pd.DataFrame, cell_deg: float, min_years: int) -> pd.DataFrame:
    """
    Celdas estáticas a partir de las detecciones type 1/2 (columnas latitude, longitude, year, sensor, type).
    Una celda entra si tuvo type 1/2 en al menos min_years años distintos.
    Devuelve una fila por celda: key, lat_c, lon_c, n_years, n_detections, sensors, types.
    """
    p = points.assign(key=_grid_keys(points["latitude"], points["longitude"], cell_deg))
    cells = p.groupby("key").agg(
        n_years=("year", "nunique"),
        n_detections=("year", "size"),
        sensors=("sensor", lambda s: ",".join(sorted(s.unique()))),
        types=("type", lambda s: ",".join(str(int(t)) for t in sorted(s.unique()))),
    ).reset_index()
    cells = cells[cells["n_years"] >= min_years].copy()
    i, j = np.divmod(cells["key"].to_numpy(), _KEY_BASE)
    # divmod con negativos: j queda en [0, _KEY_BASE); se corrige para longitudes negativas
    neg = j > _KEY_BASE // 2
    i, j = np.where(neg, i + 1, i), np.where(neg, j - _KEY_BASE, j)
    cells["lat_c"] = ((i + 0.5) * cell_deg).round(4)
    cells["lon_c"] = ((j + 0.5) * cell_deg).round(4)
    return cells[["key", "lat_c", "lon_c", "n_years", "n_detections", "sensors", "types"]].reset_index(drop=True)


def static_mask_keys(mask: pd.DataFrame, buffer_cells: int) -> np.ndarray:
    """Claves de las celdas estáticas más un margen de buffer_cells celdas alrededor de cada una."""
    base = mask["key"].to_numpy()
    offsets = [di * _KEY_BASE + dj
               for di in range(-buffer_cells, buffer_cells + 1)
               for dj in range(-buffer_cells, buffer_cells + 1)]
    return np.unique(np.concatenate([base + off for off in offsets])) if len(base) else base


def flag_static(df: pd.DataFrame, keys: np.ndarray, cell_deg: float) -> pd.Series:
    """True si el punto cae en una celda de la máscara (con su margen)."""
    return _grid_keys(df["latitude"], df["longitude"], cell_deg).isin(keys)
