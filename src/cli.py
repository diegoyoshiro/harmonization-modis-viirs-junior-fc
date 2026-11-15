"""
Interfaz de línea de comandos (CLI) del pipeline FIRMS.

Comandos principales:
    audit     : Ejecuta diagnóstico de calidad de archivos y genera reportes en output/reports/.
    build     : Genera las tablas diaria y semanales agregadas en output/interim/.
    calibrate : Calibra el GLM semanal Aqua -> S-NPP, valida en años retenidos y guarda
                el factor final en output/processed/ (requiere haber ejecutado build).

Comandos previstos (stubs):
    harmonize   : Armonización de la serie histórica.
    climatology : Cálculo de climatología y anomalías.
    export      : Exportación de datos para el frontend web.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aggregate import load_table, run_build
from audit import run_audit
from calibration import run_calibration, years_from_window
from config import (
    INTERIM_DIR,
    MODIS_DIR,
    NOAA20_DIR,
    NOAA21_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    SNPP_DIR,
    SOURCES,
    WINDOWS,
    YEAR_MAX,
    YEAR_MIN,
)
from io_firms import find_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["audit", "build", "calibrate", "harmonize", "climatology", "export"])
    parser.add_argument("--modis-dir", help=f"carpeta de MODIS (por defecto {MODIS_DIR})")
    parser.add_argument("--snpp-dir", help=f"carpeta de S-NPP (por defecto {SNPP_DIR})")
    parser.add_argument("--noaa20-dir", help=f"carpeta de NOAA-20 (por defecto {NOAA20_DIR}; opcional)")
    parser.add_argument("--noaa21-dir", help=f"carpeta de NOAA-21 (por defecto {NOAA21_DIR}; opcional)")
    parser.add_argument("--out-dir", default=None,
                        help="carpeta de salida (por defecto output/reports para audit, output/interim "
                             "para build, output/processed para calibrate)")
    parser.add_argument("--years", type=int, nargs="+",
                        help="usar solo estos años (ignora el rango del script)")
    parser.add_argument("--all-years", action="store_true",
                        help="ignorar el rango YEAR_MIN-YEAR_MAX y usar todos los archivos")
    args = parser.parse_args()

    # Comandos stub
    if args.command in ["harmonize", "climatology", "export"]:
        raise NotImplementedError(f"El comando '{args.command}' está planificado como módulo stub.")

    # Comandos que parten de las tablas de output/interim (no leen los CSV crudos)
    if args.command == "calibrate":
        weekly = load_table(INTERIM_DIR, "weekly_sensor")
        run_calibration(
            weekly,
            calibration_years=years_from_window(WINDOWS["calibration"]),
            validation_years=years_from_window(WINDOWS["validation"]),
            final_years=years_from_window(WINDOWS["final"]),
            out_dir=Path(args.out_dir) if args.out_dir else PROCESSED_DIR,
            plot_dir=REPORTS_DIR,
        )
        return

    source_dirs = {
        "modis": Path(args.modis_dir) if args.modis_dir else MODIS_DIR,
        "snpp": Path(args.snpp_dir) if args.snpp_dir else SNPP_DIR,
        "noaa20": Path(args.noaa20_dir) if args.noaa20_dir else NOAA20_DIR,
        "noaa21": Path(args.noaa21_dir) if args.noaa21_dir else NOAA21_DIR,
    }
    if args.years:
        years, label = sorted(set(args.years)), f"años {sorted(set(args.years))}"
    elif args.all_years or (YEAR_MIN is None and YEAR_MAX is None):
        years, label = None, "todos los años"
    else:
        lo = YEAR_MIN if YEAR_MIN is not None else 0
        hi = YEAR_MAX if YEAR_MAX is not None else 9999
        years, label = list(range(lo, hi + 1)), f"rango {YEAR_MIN}-{YEAR_MAX}"

    print(f"Se procesan: {label}")
    files = find_files(source_dirs, years)
    print(f"Archivos encontrados: {len(files)}")
    for key in SOURCES:
        names = [f["path"].name for f in files if f["source"] == key]
        if names:
            print(f"  {key}: {len(names)} archivos ({names[0]} ... {names[-1]})")

    if args.command == "audit":
        out_dir = Path(args.out_dir) if args.out_dir else REPORTS_DIR
        run_audit(files, out_dir)
    elif args.command == "build":
        out_dir = Path(args.out_dir) if args.out_dir else INTERIM_DIR
        # La máscara de fuentes estáticas se construye siempre con todos los años disponibles
        mask_files = find_files(source_dirs) if years else files
        run_build(files, out_dir, mask_files=mask_files)


if __name__ == "__main__":
    main()
