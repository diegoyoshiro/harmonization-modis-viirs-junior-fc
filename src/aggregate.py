"""
Módulo de agregación espacial y temporal de datos FIRMS.
Construcción de tabla diaria agregada por celda, fecha local y sensor.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from io_firms import load


def aggregate_daily(df: pd.DataFrame) -> pd.DataFrame:
    """
    Conserva solo type==0 y agrega por día local x celda x sensor.
    Guarda dos versiones para poder decidir la confianza sin reprocesar:
      count / total_frp                -> sin baja confianza
      count_with_low / total_frp_with_low -> con todo
    """
    d = df[df["is_veg"]].copy()
    d["count_ok"] = (~d["is_low"]).astype(int)
    d["frp_ok"] = d["frp"].where(~d["is_low"], 0.0)
    out = d.groupby(
        ["local_date", "cell", "lat_c", "lon_c", "sensor", "family"],
        as_index=False
    ).agg(
        count=("count_ok", "sum"),
        count_with_low=("frp", "size"),
        total_frp=("frp_ok", "sum"),
        total_frp_with_low=("frp", "sum"),
    )
    return out


def run_build(files: list[dict], out_dir: Path) -> None:
    """Ejecuta el pipeline de build para generar la tabla agregada diaria."""
    parts, report, failures = [], [], []
    for info in files:
        name = info["path"].name
        try:
            df, stats = load(info)
        except Exception as exc:  # un archivo malo no debe frenar el resto
            failures.append((name, str(exc)))
            print(f"  [ERROR] {name}: {exc}")
            continue
        daily = aggregate_daily(df)
        parts.append(daily)
        report.append({
            "file": name, **stats, "rows_daily": len(daily),
            "count": int(daily["count"].sum())
        })
        print(f"  OK {name}: {stats['rows_raw']} filas -> {len(daily)} filas diarias")

    if not parts:
        sys.exit("No se pudo procesar ningún archivo.")
    result = pd.concat(parts, ignore_index=True)
    # Un archivo anual puede traer días del año vecino por el cambio UTC -> local: se reagrupa.
    keys = ["local_date", "cell", "lat_c", "lon_c", "sensor", "family"]
    result = result.groupby(keys, as_index=False).sum(numeric_only=True)
    result = result.sort_values(["local_date", "sensor", "cell"]).reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        target = out_dir / "daily_cell_sensor.parquet"
        result.to_parquet(target, index=False)
    except ImportError:
        target = out_dir / "daily_cell_sensor.csv.gz"
        result.to_csv(target, index=False)
        print("  (pyarrow no instalado: se guardó CSV comprimido. Instala con: pip install pyarrow)")
    pd.DataFrame(report).to_csv(out_dir / "build_summary.csv", index=False)
    print(f"\nTabla diaria: {len(result)} filas -> {target}")
    if failures:
        print(f"Archivos con error ({len(failures)}):")
        for name, msg in failures:
            print(f"  - {name}: {msg}")


def aggregate_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    STUB: Agrega la tabla diaria a nivel semanal ISO (semana x celda x sensor).
    Entradas:
        df_daily: DataFrame generado por aggregate_daily / daily_cell_sensor.
    Salidas:
        DataFrame agregado a nivel semanal para calibración y climatología.
    """
    raise NotImplementedError("aggregate_weekly no implementado aún.")
