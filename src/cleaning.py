"""
Módulo de limpieza, estandarización y filtrado de datos FIRMS.
Funciones puras de transformación sobre DataFrames sin acceso directo a disco.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import CELL_SIZE, UTC_OFFSET_HOURS


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

    # Confianza
    df["confidence_cat"] = confidence_to_category(df["confidence"], info["family"] == "MODIS")
    df["is_low"] = df["confidence_cat"].eq("low")

    # Celda 0,25° (se guarda el CENTRO)
    i = np.floor(df["latitude"] / CELL_SIZE)
    j = np.floor(df["longitude"] / CELL_SIZE)
    df["lat_c"] = ((i + 0.5) * CELL_SIZE).round(4)
    df["lon_c"] = ((j + 0.5) * CELL_SIZE).round(4)
    df["cell"] = df["lat_c"].map("{:.3f}".format) + "_" + df["lon_c"].map("{:.3f}".format)
    return df
