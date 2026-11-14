"""
Módulo de entrada/salida de datos FIRMS.
Búsqueda de archivos en carpetas por sensor y carga de DataFrames estandarizados.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from cleaning import standardize
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


def load(info: dict) -> tuple[pd.DataFrame, dict]:
    """Lee un archivo y devuelve el DataFrame estandarizado (sin filtrar) y estadísticas crudas."""
    df = pd.read_csv(info["path"], low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"faltan columnas {missing}. Encontradas: {list(df.columns)}")

    stats = {"rows_raw": len(df)}
    df = standardize(df, info, stats)
    return df, stats
