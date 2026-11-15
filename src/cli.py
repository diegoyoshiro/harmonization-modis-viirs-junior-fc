"""
Interfaz de línea de comandos (CLI) del pipeline FIRMS.

Comandos principales:
    audit     : Ejecuta diagnóstico de calidad de archivos y genera reportes en output/reports/.
    build     : Genera las tablas diaria y semanales agregadas en output/interim/.
    calibrate : Calibra el GLM semanal Aqua -> S-NPP, valida en años retenidos y guarda
                el factor final en output/processed/ (requiere haber ejecutado build).
    validate  : Repite solo la validación (S-NPP y NOAA-20, año a año) con los factores de
                output/processed/calibration_factors.csv (requiere haber ejecutado calibrate).

    harmonize : Serie única 2002-hoy: Aqua × factor (2002-2011, "estimado") + VIIRS real
                (S-NPP, NOAA-20 de respaldo), nacional y por celda (requiere calibrate).
    climatology : Línea base 2003-2024, anomalías, ranking anual y calendario año × mes (Perú y
                áreas de interés de settings.yaml); requiere harmonize.
    export      : JSON por vista para el frontend en output/web/ (contrato en docs/frontend_datos.md);
                requiere climatology.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aggregate import load_table, run_build
from audit import run_audit
from calibration import run_calibration, years_from_window
from validation import run_validation
from harmonize import run_harmonization
from climatology import run_climatology
from export_web import run_export
from config import (
    INTERIM_DIR,
    MODIS_DIR,
    NOAA20_DIR,
    NOAA21_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    SNPP_DIR,
    SOURCES,
    WEB_DIR,
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
    parser.add_argument("command", choices=["audit", "build", "calibrate", "validate", "harmonize", "climatology", "export"])
    parser.add_argument("--modis-dir", help=f"carpeta de MODIS (por defecto {MODIS_DIR})")
    parser.add_argument("--snpp-dir", help=f"carpeta de S-NPP (por defecto {SNPP_DIR})")
    parser.add_argument("--noaa20-dir", help=f"carpeta de NOAA-20 (por defecto {NOAA20_DIR}; opcional)")
    parser.add_argument("--noaa21-dir", help=f"carpeta de NOAA-21 (por defecto {NOAA21_DIR}; opcional)")
    parser.add_argument("--out-dir", default=None,
                        help="carpeta de salida (por defecto output/reports para audit, output/interim "
                             "para build, output/processed para calibrate, validate, harmonize y climatology, "
                             "output/web para export)")
    parser.add_argument("--years", type=int, nargs="+",
                        help="usar solo estos años (ignora el rango del script)")
    parser.add_argument("--all-years", action="store_true",
                        help="ignorar el rango YEAR_MIN-YEAR_MAX y usar todos los archivos")
    args = parser.parse_args()

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
    if args.command == "validate":
        import pandas as pd
        out_dir = Path(args.out_dir) if args.out_dir else PROCESSED_DIR
        factors_path = PROCESSED_DIR / "calibration_factors.csv"
        if not factors_path.exists():
            sys.exit(f"No existe {factors_path}: ejecuta primero 'calibrate'.")
        run_validation(pd.read_csv(factors_path), load_table(INTERIM_DIR, "weekly_sensor"),
                       years_from_window(WINDOWS["validation"]), out_dir)
        return
    if args.command == "harmonize":
        import json
        import pandas as pd
        out_dir = Path(args.out_dir) if args.out_dir else PROCESSED_DIR
        needed = ["harmonization_factors.csv", "calibration_factors.csv", "calibration_summary.json"]
        absent = [n for n in needed if not (PROCESSED_DIR / n).exists()]
        if absent:
            sys.exit(f"Faltan {absent} en {PROCESSED_DIR}: ejecuta primero 'calibrate'.")
        chosen = json.loads((PROCESSED_DIR / "calibration_summary.json").read_text(encoding="utf-8"))["chosen_model"]
        run_harmonization(
            load_table(INTERIM_DIR, "weekly_sensor"),
            load_table(INTERIM_DIR, "weekly_cell_sensor"),
            final_factors=pd.read_csv(PROCESSED_DIR / "harmonization_factors.csv"),
            calibration_factors=pd.read_csv(PROCESSED_DIR / "calibration_factors.csv"),
            model=chosen,
            validation_years=years_from_window(WINDOWS["validation"]),
            out_dir=out_dir,
            plot_dir=REPORTS_DIR,
            df_daily=load_table(INTERIM_DIR, "daily_cell_sensor"),
        )
        return
    if args.command == "climatology":
        import pandas as pd
        out_dir = Path(args.out_dir) if args.out_dir else PROCESSED_DIR
        needed = ["harmonized_weekly.csv", "harmonized_monthly.csv"]
        absent = [n for n in needed if not (PROCESSED_DIR / n).exists()]
        if absent:
            sys.exit(f"Faltan {absent} en {PROCESSED_DIR}: ejecuta primero 'harmonize'.")
        try:
            monthly_cell = load_table(PROCESSED_DIR, "harmonized_monthly_cell")
        except FileNotFoundError:
            monthly_cell = None
        run_climatology(
            pd.read_csv(PROCESSED_DIR / "harmonized_weekly.csv", parse_dates=["week"]),
            pd.read_csv(PROCESSED_DIR / "harmonized_monthly.csv"),
            monthly_cell,
            out_dir=out_dir,
            plot_dir=REPORTS_DIR,
        )
        return
    if args.command == "export":
        needed = ["anomalies_monthly.csv", "anomalies_weekly.csv", "climatology_monthly.csv",
                  "climatology_weekly.csv", "annual_ranking.csv", "harmonize_summary.json"]
        absent = [n for n in needed if not (PROCESSED_DIR / n).exists()]
        if absent:
            sys.exit(f"Faltan {absent} en {PROCESSED_DIR}: ejecuta primero 'harmonize' y 'climatology'.")
        try:
            monthly_cell = load_table(PROCESSED_DIR, "harmonized_monthly_cell")
        except FileNotFoundError:
            monthly_cell = None
        run_export(PROCESSED_DIR, Path(args.out_dir) if args.out_dir else WEB_DIR, monthly_cell)
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
