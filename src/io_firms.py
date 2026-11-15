"""
Módulo de entrada/salida de datos FIRMS.
Búsqueda de archivos en carpetas por sensor y carga de DataFrames estandarizados.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from cleaning import assign_modis_sensor, flag_static, standardize
from config import OPTIONAL_SOURCES, REQUIRED, SOURCES


def find_files(source_dirs: dict[str, Path | None], years: list[int] | None = None) -> list[dict]:
    """Busca los CSV de cada sensor en su propia carpeta. Las carpetas None se omiten."""
    found = []
    for key, folder in source_dirs.items():
        if folder is None:
            continue
        folder = Path(folder)
        if not folder.is_dir():
            if key in OPTIONAL_SOURCES:
                print(f"Nota: no existe la carpeta de {key} ('{folder}'); se omite.")
                continue
            sys.exit(f"Error: la carpeta de {key} ('{folder}') no existe.")
        spec = SOURCES[key]
        pattern = re.compile(rf"^{spec['prefix']}_(\d{{4}})_peru\.csv$", re.IGNORECASE)
        count = 0
        for path in sorted(folder.iterdir()):
            match = pattern.match(path.name)
            if not match:
                continue
            year = int(match.group(1))
            if years and year not in years:
                continue
            found.append({
                "path": path, "source": key, "year": year,
                "family": spec["family"], "sensor": spec["sensor"]
            })
            count += 1
        if count == 0:
            print(f"Aviso: no hay archivos de {key} en '{folder}' "
                  f"(se espera {spec['prefix'].replace('(?:', '(')}_AAAA_Peru.csv).")
    if not found:
        sys.exit("Error: no se encontró ningún archivo. Revisa las rutas de las carpetas.")
    return found


def collect_static_points(files: list[dict]) -> pd.DataFrame:
    """
    Lee solo las detecciones type 1 (volcán) o 2 (fuente estática) de todos los archivos.
    Columnas: latitude, longitude, year, sensor, type. Los archivos sin columna 'type' se omiten.
    """
    wanted = {"latitude", "longitude", "acq_date", "type", "satellite"}
    parts = []
    for info in files:
        try:
            df = pd.read_csv(info["path"], usecols=lambda c: c.strip().lower() in wanted, low_memory=False)
        except Exception as exc:  # el error real se reporta al cargar el archivo completo
            print(f"  [AVISO máscara] {info['path'].name}: {exc}")
            continue
        df.columns = [c.strip().lower() for c in df.columns]
        if "type" not in df.columns:
            continue
        df["type"] = pd.to_numeric(df["type"], errors="coerce")
        df = df[df["type"].isin([1, 2])]
        if df.empty:
            continue
        sensor = assign_modis_sensor(df) if info["sensor"] is None else info["sensor"]
        parts.append(pd.DataFrame({
            "latitude": pd.to_numeric(df["latitude"], errors="coerce"),
            "longitude": pd.to_numeric(df["longitude"], errors="coerce"),
            "year": df["acq_date"].astype(str).str.slice(0, 4).astype(int),
            "sensor": sensor,
            "type": df["type"].astype(int),
        }).dropna(subset=["latitude", "longitude"]))
    cols = ["latitude", "longitude", "year", "sensor", "type"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


def load(info: dict, static_keys=None, cell_deg: float | None = None) -> tuple[pd.DataFrame, dict]:
    """
    Lee un archivo y devuelve el DataFrame estandarizado (sin filtrar) y estadísticas crudas.
    Si se pasan static_keys (cleaning.static_mask_keys) y cell_deg, añade la columna is_static_loc.
    """
    df = pd.read_csv(info["path"], low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"faltan columnas {missing}. Encontradas: {list(df.columns)}")

    stats = {"rows_raw": len(df)}
    df = standardize(df, info, stats)
    if static_keys is not None:
        df["is_static_loc"] = flag_static(df, static_keys, cell_deg)
        stats["static_loc_removed"] = int((df["is_veg"] & df["is_static_loc"]).sum())
    return df, stats
