"""
Módulo de agregación espacial y temporal de datos FIRMS.
Construcción de tabla diaria agregada por celda, fecha local y sensor,
y de las tablas semanales (ISO) que alimentan la calibración y la climatología.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from cleaning import CELL_COLS, build_static_mask, static_mask_keys
from config import OUTAGES, SEASONS, STATIC_MASK
from io_firms import collect_static_points, load

# nrt_count: detecciones (con baja confianza) del producto NRT, preliminar. No es una métrica de fuego:
# solo sirve para saber qué días/semanas son preliminares (harmonize.nrt_start).
METRICS = ["count", "count_with_low", "total_frp", "total_frp_with_low", "nrt_count"]


def aggregate_daily(df: pd.DataFrame) -> pd.DataFrame:
    """
    Conserva solo type==0 fuera de la máscara de fuentes estáticas (si existe la columna
    is_static_loc) y agrega por día local x celda x sensor.
    Guarda dos versiones para poder decidir la confianza sin reprocesar:
      count / total_frp                -> sin baja confianza
      count_with_low / total_frp_with_low -> con todo
    """
    keep = df["is_veg"]
    if "is_static_loc" in df.columns:
        keep = keep & ~df["is_static_loc"]
    d = df[keep].copy()
    d["count_ok"] = (~d["is_low"]).astype(int)
    d["nrt"] = d["is_nrt"].astype(int) if "is_nrt" in d else 0
    d["frp_ok"] = d["frp"].where(~d["is_low"], 0.0)
    out = d.groupby(
        ["local_date", *CELL_COLS, "sensor", "family"],
        as_index=False
    ).agg(
        count=("count_ok", "sum"),
        count_with_low=("frp", "size"),
        total_frp=("frp_ok", "sum"),
        total_frp_with_low=("frp", "sum"),
        nrt_count=("nrt", "sum"),
    )
    return out


def build_mask(mask_files: list[dict], out_dir: Path):
    """
    Construye la máscara de fuentes estáticas con todos los archivos disponibles (no solo los
    años procesados, para que la máscara no dependa de --years) y la guarda en static_mask.
    Devuelve las claves de celda (con margen) o None si la máscara está desactivada.
    """
    if not STATIC_MASK["enabled"]:
        print("Máscara de fuentes estáticas: desactivada (settings.yaml -> static_mask.enabled)")
        return None
    points = collect_static_points(mask_files)
    mask = build_static_mask(points, STATIC_MASK["cell_deg"], STATIC_MASK["min_years"])
    keys = static_mask_keys(mask, STATIC_MASK["buffer_cells"])
    out_dir.mkdir(parents=True, exist_ok=True)
    target = save_table(mask, out_dir, "static_mask")
    print(f"Máscara de fuentes estáticas: {len(points)} detecciones type 1/2 -> {len(mask)} celdas de "
          f"{STATIC_MASK['cell_deg']}° con >= {STATIC_MASK['min_years']} años "
          f"({len(keys)} con margen de {STATIC_MASK['buffer_cells']}) -> {target}")
    return keys


def run_build(files: list[dict], out_dir: Path, mask_files: list[dict] | None = None) -> None:
    """
    Ejecuta el pipeline de build para generar las tablas diaria y semanales.
    mask_files: archivos con los que se construye la máscara de fuentes estáticas (por defecto, files).
    """
    static_keys = build_mask(mask_files or files, out_dir)
    parts, report, failures = [], [], []
    for info in files:
        name = info["path"].name
        try:
            df, stats = load(info, static_keys, STATIC_MASK["cell_deg"])
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
    keys = ["local_date", *CELL_COLS, "sensor", "family"]
    result = result.groupby(keys, as_index=False).sum(numeric_only=True)
    result = result.sort_values(["local_date", "sensor", "cell"]).reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    target = save_table(result, out_dir, "daily_cell_sensor")
    pd.DataFrame(report).to_csv(out_dir / "build_summary.csv", index=False)
    print(f"\nTabla diaria: {len(result)} filas -> {target}")

    for level, name in [("national", "weekly_sensor"), ("cell", "weekly_cell_sensor")]:
        weekly = aggregate_weekly(result, level=level)
        target = save_table(weekly, out_dir, name)
        print(f"Tabla semanal ({level}): {len(weekly)} filas -> {target}")

    if failures:
        print(f"Archivos con error ({len(failures)}):")
        for name, msg in failures:
            print(f"  - {name}: {msg}")


def save_table(df: pd.DataFrame, out_dir: Path, name: str) -> Path:
    """Guarda en parquet si pyarrow está disponible; si no, en CSV comprimido."""
    try:
        target = out_dir / f"{name}.parquet"
        df.to_parquet(target, index=False)
    except ImportError:
        target = out_dir / f"{name}.csv.gz"
        df.to_csv(target, index=False)
        print("  (pyarrow no instalado: se guardó CSV comprimido. Instala con: pip install pyarrow)")
    return target


def load_table(out_dir: Path, name: str) -> pd.DataFrame:
    """Lee una tabla guardada con save_table (parquet o csv.gz)."""
    parquet = out_dir / f"{name}.parquet"
    if parquet.is_file():
        return pd.read_parquet(parquet)
    csv = out_dir / f"{name}.csv.gz"
    if csv.is_file():
        df = pd.read_csv(csv)
        for col in ("local_date", "week"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        return df
    raise FileNotFoundError(f"No existe {parquet} ni {csv}. Ejecuta primero: python src/cli.py build")


def _week_start(dates: pd.Series) -> pd.Series:
    """Lunes de la semana ISO de cada fecha local."""
    d = pd.to_datetime(dates).dt.normalize()
    return d - pd.to_timedelta(d.dt.weekday, unit="D")


def _add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Añade año/semana ISO, mes y temporada. El mes es el del jueves (regla ISO)."""
    iso = df["week"].dt.isocalendar()
    df["iso_year"] = iso["year"].astype(int)
    df["iso_week"] = iso["week"].astype(int)
    df["month"] = (df["week"] + pd.Timedelta(days=3)).dt.month
    month_to_season = {m: name for name, months in SEASONS.items() for m in months}
    df["season"] = df["month"].map(month_to_season).fillna("sin_temporada")
    return df


def _in_outage(df: pd.DataFrame) -> pd.Series:
    """True si la semana (lunes-domingo) se solapa con un apagón documentado del sensor (OUTAGES)."""
    flag = pd.Series(False, index=df.index)
    week_end = df["week"] + pd.Timedelta(days=6)
    for sensor, (start, end) in OUTAGES.items():
        overlap = (df["week"] <= pd.Timestamp(end)) & (week_end >= pd.Timestamp(start))
        flag |= df["sensor"].eq(sensor) & overlap
    return flag


def _sensor_weeks(d: pd.DataFrame) -> pd.DataFrame:
    """
    Semanas en que cada sensor está operativo (de su primera a su última semana con datos)
    y cuántos días de esa semana tuvo al menos una detección en todo el dominio.
    days_with_data = 0 indica una semana sin observaciones: probable hueco, no "cero fuegos".
    """
    cov = d.groupby(["sensor", "family", "week"])["local_date"].nunique().rename("days_with_data")
    frames = []
    for (sensor, family), g in cov.groupby(level=["sensor", "family"]):
        weeks = g.index.get_level_values("week")
        full = pd.date_range(weeks.min(), weeks.max(), freq="7D")
        frames.append(pd.DataFrame({
            "sensor": sensor, "family": family, "week": full,
            "days_with_data": g.droplevel(["sensor", "family"]).reindex(full, fill_value=0).to_numpy(),
        }))
    return pd.concat(frames, ignore_index=True)


def aggregate_weekly(df_daily: pd.DataFrame, level: str = "national") -> pd.DataFrame:
    """
    Agrega la tabla diaria a semana ISO (lunes a domingo, hora local) con ceros explícitos.

    level="national": una fila por semana x sensor (todo el dominio). Métricas:
        count, count_with_low, total_frp, total_frp_with_low,
        active_cells (celdas con count > 0), days_with_data.
        Cada sensor tiene todas las semanas entre su inicio y su fin; las que no tienen
        detecciones aparecen con 0 (omitirlas sesgaría el GLM hacia arriba).
    level="cell": una fila por semana x celda x sensor. Para cada semana, el universo de celdas
        es la unión de celdas con alguna detección (de cualquier sensor) esa semana, cruzada con
        los sensores operativos esa semana; así cada par Aqua/VIIRS de una celda tiene su cero.
        Métricas: las cuatro de la tabla diaria, active_days (días con count > 0) y days_with_data.

    Columnas de calendario en ambos niveles: week (lunes), iso_year, iso_week, month, season.
    Para filtrar ventanas de calibración/validación usar iso_year.
    """
    if level not in ("national", "cell"):
        raise ValueError(f"level debe ser 'national' o 'cell', no {level!r}")

    d = df_daily.copy()
    d["week"] = _week_start(d["local_date"])
    sensor_weeks = _sensor_weeks(d)

    if level == "national":
        agg = d.groupby(["week", "sensor"], as_index=False)[METRICS].sum()
        # Celdas activas en la malla de análisis (0.25°) para que el valor sea comparable entre épocas
        active = (d[d["count"] > 0].groupby(["week", "sensor"])["cell_025"].nunique()
                  .rename("active_cells").reset_index())
        out = (sensor_weeks.merge(agg, on=["week", "sensor"], how="left")
               .merge(active, on=["week", "sensor"], how="left"))
        out[METRICS + ["active_cells"]] = out[METRICS + ["active_cells"]].fillna(0)
        out = out.astype({"count": int, "count_with_low": int, "nrt_count": int, "active_cells": int})
        cols = ["week", "sensor", "family"]
    else:
        keys = ["week", *CELL_COLS, "sensor"]
        d["active_day"] = (d["count"] > 0).astype(int)
        agg = (d.groupby(keys, as_index=False)[METRICS + ["active_day"]].sum()
               .rename(columns={"active_day": "active_days"}))
        cells = d[["week", *CELL_COLS]].drop_duplicates()
        grid = cells.merge(sensor_weeks, on="week", how="inner")
        out = grid.merge(agg, on=keys, how="left")
        out[METRICS + ["active_days"]] = out[METRICS + ["active_days"]].fillna(0)
        out = out.astype({"count": int, "count_with_low": int, "nrt_count": int, "active_days": int})
        cols = ["week", *CELL_COLS, "sensor", "family"]

    out = _add_calendar(out)
    out["in_outage"] = _in_outage(out)
    order = cols + [c for c in out.columns if c not in cols]
    return out[order].sort_values(cols).reset_index(drop=True)
