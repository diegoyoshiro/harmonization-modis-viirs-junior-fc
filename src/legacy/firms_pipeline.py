"""
Pipeline FIRMS (Perú): auditoría de datos y tabla diaria por celda y sensor.

Carpetas de entrada (una por sensor; un archivo por año dentro de cada una):
    MODIS_DIR/modis_{anio}_Peru.csv         (Terra + Aqua juntos, columna 'satellite')
    SNPP_DIR/viirs-snpp_{anio}_Peru.csv     (S-NPP)
    NOAA20_DIR/viirs-jpss1_{anio}_Peru.csv  (NOAA-20; opcional: se usa si la carpeta existe)
    NOAA21_DIR/viirs-jpss2_{anio}_Peru.csv  (NOAA-21; opcional: se usa si la carpeta existe)
Por defecto solo procesa los años YEAR_MIN-YEAR_MAX (2012-2017). Usa dataset/modis, dataset/snpp, dataset/noaa20 y dataset/noaa21 junto a src/. Edita las rutas en
CONFIGURACIÓN o pásalas por línea de comandos.

Comandos:
    python firms_pipeline.py audit
    python firms_pipeline.py audit --modis-dir D:/datos/modis --snpp-dir D:/datos/snpp
    python firms_pipeline.py build --out-dir salida --years 2012 2013 2014
    python firms_pipeline.py audit --all-years      # ignora el rango 2012-2017

  audit : NO modifica nada. Revisa cada archivo (por sensor y año) y escribe
          tablas de diagnóstico + alertas automáticas.
  build : limpia y escribe daily_cell_sensor.parquet (o .csv.gz si no hay pyarrow),
          una fila por día local x celda x sensor. Todo Perú; el recorte a Cusco
          se hace después filtrando lat_c / lon_c.

Columnas requeridas: latitude, longitude, acq_date, acq_time (HHMM UTC), frp, confidence.
Opcionales: satellite, daynight, type.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# CONFIGURACIÓN
# ----------------------------------------------------------------------------
# Rutas relativas a la raíz del proyecto (la carpeta que contiene src/ y dataset/),
# así el script funciona sin importar desde dónde lo ejecutes.
#   proyecto/
#     dataset/modis/    modis_{anio}_Peru.csv
#     dataset/snpp/     viirs-snpp_{anio}_Peru.csv
#     dataset/noaa20/   viirs-jpss1_{anio}_Peru.csv   (opcional)
#     dataset/noaa21/   viirs-jpss2_{anio}_Peru.csv   (opcional)
#     src/firms_pipeline.py
# Nota: al moverse este archivo a src/legacy/, PROJECT_ROOT sube 3 niveles hasta la raíz del proyecto.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset"
MODIS_DIR = DATASET_DIR / "modis"
SNPP_DIR = DATASET_DIR / "snpp"
NOAA20_DIR = DATASET_DIR / "noaa20"
NOAA21_DIR = DATASET_DIR / "noaa21"
DEFAULT_OUT_DIR = PROJECT_ROOT / "output"

# Rango de años que se procesa (ambos incluidos). None en un extremo = sin límite.
# Se puede cambiar por línea de comandos con --years (lista exacta) o --all-years.
YEAR_MIN = 2012
YEAR_MAX = 2017

# Sensores opcionales: si su carpeta no existe, se omiten sin error.
# (Pon una ruta en None para desactivar un sensor aunque su carpeta exista.)
OPTIONAL_SOURCES = {"noaa20", "noaa21"}

UTC_OFFSET_HOURS = -5          # Perú
CELL_SIZE = 0.25               # grados
REQUIRED = ["latitude", "longitude", "acq_date", "acq_time", "frp", "confidence"]
PERU_BBOX = dict(lat_min=-18.5, lat_max=0.1, lon_min=-81.5, lon_max=-68.5)

# Alertas
MAX_GAP_DAYS = 3               # huecos internos mayores se reportan
MAX_LOW_CONF_PCT = 40.0
MAX_PASS_SHIFT_MIN = 60        # cambio de hora de paso vs. primer año del sensor
MAX_YOY_RATIO_CHANGE = 0.30    # cambio interanual de la razón Terra/Aqua

# fuente -> familia, sensor fijo (None = se lee de 'satellite') y prefijo del nombre de archivo
SOURCES = {
    "modis":  dict(family="MODIS", sensor=None,     prefix="modis"),
    "snpp":   dict(family="VIIRS", sensor="SNPP",   prefix="viirs-snpp"),
    "noaa20": dict(family="VIIRS", sensor="NOAA20", prefix="viirs-(?:jpss1|noaa20)"),
    "noaa21": dict(family="VIIRS", sensor="NOAA21", prefix="viirs-(?:jpss2|noaa21)"),
}


# ----------------------------------------------------------------------------
# CARGA Y ESTANDARIZACIÓN
# ----------------------------------------------------------------------------
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
            found.append({"path": path, "source": key, "year": year,
                          "family": spec["family"], "sensor": spec["sensor"]})
            count += 1
        if count == 0:
            print(f"Aviso: no hay archivos de {key} en '{folder}' "
                  f"(se espera {spec['prefix'].replace('(?:', '(')}_AAAA_Peru.csv).")
    if not found:
        sys.exit("Error: no se encontró ningún archivo. Revisa las rutas de las carpetas.")
    return found


def confidence_to_category(series: pd.Series, is_modis: bool) -> pd.Series:
    """MODIS: 0-100 numérico. VIIRS: l / n / h. Devuelve low / medium / high."""
    numeric = pd.to_numeric(series, errors="coerce")
    if is_modis or numeric.notna().mean() > 0.9:
        cat = pd.cut(numeric, bins=[-1, 29, 79, 100], labels=["low", "medium", "high"])
        return cat.astype("object")
    mapping = {"l": "low", "low": "low", "n": "medium", "nominal": "medium",
               "h": "high", "high": "high"}
    return series.astype(str).str.strip().str.lower().map(mapping)


def assign_modis_sensor(df: pd.DataFrame) -> pd.Series:
    if "satellite" not in df.columns:
        return pd.Series("MODIS_desconocido", index=df.index)
    sat = df["satellite"].astype(str).str.strip().str.lower()
    out = pd.Series("MODIS_desconocido", index=df.index)
    out[sat.isin(["aqua", "a"])] = "Aqua"
    out[sat.isin(["terra", "t"])] = "Terra"
    return out


def load(info: dict) -> tuple[pd.DataFrame, dict]:
    """Lee un archivo y devuelve el DataFrame estandarizado (sin filtrar) y estadísticas crudas."""
    df = pd.read_csv(info["path"], low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"faltan columnas {missing}. Encontradas: {list(df.columns)}")

    stats = {"rows_raw": len(df)}
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
    return df, stats


# ----------------------------------------------------------------------------
# BUILD: tabla diaria por celda y sensor
# ----------------------------------------------------------------------------
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
    out = d.groupby(["local_date", "cell", "lat_c", "lon_c", "sensor", "family"],
                    as_index=False).agg(
        count=("count_ok", "sum"),
        count_with_low=("frp", "size"),
        total_frp=("frp_ok", "sum"),
        total_frp_with_low=("frp", "sum"),
    )
    return out


def run_build(files: list[dict], out_dir: Path) -> None:
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
        report.append({"file": name, **stats, "rows_daily": len(daily),
                       "count": int(daily["count"].sum())})
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


# ----------------------------------------------------------------------------
# AUDIT
# ----------------------------------------------------------------------------
def hhmm(minutes: float) -> str:
    return "" if pd.isna(minutes) else f"{int(minutes // 60):02d}:{int(minutes % 60):02d}"


def audit_group(sub: pd.DataFrame, info: dict, sensor: str, stats: dict) -> dict:
    """Una fila de diagnóstico por sensor y archivo (año)."""
    veg = sub[sub["is_veg"]]
    clean = veg[~veg["is_low"]]

    days = pd.DatetimeIndex(np.sort(sub["acq_day"].unique()))
    if len(days) > 1:
        gaps = np.diff(days.values).astype("timedelta64[D]").astype(int) - 1
        longest_gap, internal_missing = int(gaps.max()), int(gaps.sum())
    else:
        longest_gap, internal_missing = 0, 0

    if "daynight" in sub.columns:
        day = sub[sub["daynight"].astype(str).str.upper().eq("D")]
    else:
        day = sub[sub["local_minutes"].between(6 * 60, 18 * 60)]
    enough = len(day) >= 20
    p50 = day["local_minutes"].median() if enough else np.nan
    p10 = day["local_minutes"].quantile(0.10) if enough else np.nan
    p90 = day["local_minutes"].quantile(0.90) if enough else np.nan

    out_peru = ~(sub["latitude"].between(PERU_BBOX["lat_min"], PERU_BBOX["lat_max"])
                 & sub["longitude"].between(PERU_BBOX["lon_min"], PERU_BBOX["lon_max"]))
    n = len(sub)
    return {
        "file": info["path"].name, "sensor": sensor, "year": info["year"],
        "rows_in_group": n,
        "invalid_time_file": stats["invalid_time"],
        "duplicates_file": stats["duplicates"],
        "type_nonzero": int((~sub["is_veg"]).sum()),
        "low_conf": int(sub["is_low"].sum()),
        "low_conf_pct": round(100 * sub["is_low"].mean(), 1) if n else np.nan,
        "conf_unknown": int(sub["confidence_cat"].isna().sum()),
        "frp_null": int(sub["frp"].isna().sum()),
        "frp_p50": round(sub["frp"].median(), 2),
        "frp_p99": round(sub["frp"].quantile(0.99), 2),
        "frp_max": round(sub["frp"].max(), 1),
        "out_of_peru": int(out_peru.sum()),
        "rows_clean": len(clean),
        "date_min": days.min().date() if len(days) else None,
        "date_max": days.max().date() if len(days) else None,
        "days_with_data": len(days),
        "internal_missing_days": internal_missing,
        "longest_gap_days": longest_gap,
        "day_pass_median": hhmm(p50), "day_pass_p10": hhmm(p10), "day_pass_p90": hhmm(p90),
        "day_pass_median_min": p50,
    }


def run_audit(files: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, monthly, failures = [], [], []
    for info in files:
        name = info["path"].name
        try:
            df, stats = load(info)
        except Exception as exc:
            failures.append((name, str(exc)))
            print(f"  [ERROR] {name}: {exc}")
            continue
        for sensor, sub in df.groupby("sensor"):
            rows.append(audit_group(sub, info, sensor, stats))
        clean = df[df["is_veg"] & ~df["is_low"]]
        m = (clean.groupby(["sensor", clean["local_date"].dt.year.rename("year"),
                            clean["local_date"].dt.month.rename("month")]).size()
             .rename("count").reset_index())
        monthly.append(m)
        print(f"  revisado {name}: {len(df)} filas")

    if not rows:
        sys.exit("No se pudo auditar ningún archivo.")
    files_df = pd.DataFrame(rows).sort_values(["sensor", "year"]).reset_index(drop=True)
    monthly_df = (pd.concat(monthly).groupby(["sensor", "year", "month"], as_index=False)["count"]
                  .sum())
    annual = monthly_df.groupby(["year", "sensor"])["count"].sum().unstack("sensor").fillna(0)
    annual = annual.astype(int)

    files_df.drop(columns="day_pass_median_min").to_csv(out_dir / "audit_files.csv", index=False)
    monthly_df.to_csv(out_dir / "audit_monthly.csv", index=False)
    annual.to_csv(out_dir / "audit_annual.csv")

    ratios = build_ratios(annual)
    if not ratios.empty:
        ratios.to_csv(out_dir / "audit_ratios.csv")

    print_report(files_df, annual, ratios)
    print_alerts(files_df, annual, ratios)
    make_plots(files_df, annual, out_dir)
    if failures:
        print(f"\nArchivos con error ({len(failures)}):")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
    print(f"\nTablas guardadas en: {out_dir.resolve()}")


def build_ratios(annual: pd.DataFrame) -> pd.DataFrame:
    pairs = [("Terra", "Aqua"), ("SNPP", "Aqua"), ("NOAA20", "SNPP"), ("NOAA20", "Aqua")]
    out = pd.DataFrame(index=annual.index)
    for num, den in pairs:
        if num in annual.columns and den in annual.columns:
            ratio = annual[num].replace(0, np.nan) / annual[den].replace(0, np.nan)
            out[f"{num}/{den}"] = ratio.round(3)
    return out.dropna(how="all")


def print_report(files_df: pd.DataFrame, annual: pd.DataFrame, ratios: pd.DataFrame) -> None:
    cols = ["sensor", "year", "rows_in_group", "rows_clean", "low_conf_pct", "type_nonzero",
            "duplicates_file", "date_min", "date_max", "longest_gap_days", "day_pass_median"]
    print("\n=== AUDITORÍA POR SENSOR Y AÑO ===")
    print(files_df[cols].to_string(index=False))
    print("\n=== DETECCIONES LIMPIAS POR AÑO (hora local) ===")
    print(annual.to_string())
    if not ratios.empty:
        print("\n=== RAZONES ANUALES (conteo limpio) ===")
        print(ratios.to_string())


def print_alerts(files_df: pd.DataFrame, annual: pd.DataFrame, ratios: pd.DataFrame) -> None:
    alerts = []
    for _, r in files_df.iterrows():
        tag = f"{r['sensor']} {r['year']}"
        if r["date_min"] and (r["date_min"].month != 1 or r["date_min"].day > 3):
            alerts.append(f"{tag}: empieza el {r['date_min']} (año incompleto o serie que arranca ahí).")
        if r["date_max"] and (r["date_max"].month != 12 or r["date_max"].day < 28):
            alerts.append(f"{tag}: termina el {r['date_max']} (año incompleto).")
        if r["longest_gap_days"] > MAX_GAP_DAYS:
            alerts.append(f"{tag}: hueco de {r['longest_gap_days']} días sin datos "
                          f"({r['internal_missing_days']} días faltantes en total).")
        if r["low_conf_pct"] > MAX_LOW_CONF_PCT:
            alerts.append(f"{tag}: {r['low_conf_pct']} % de baja confianza.")
        if r["out_of_peru"] > 0:
            alerts.append(f"{tag}: {r['out_of_peru']} puntos fuera del rectángulo de Perú.")
        if r["conf_unknown"] > 0:
            alerts.append(f"{tag}: {r['conf_unknown']} filas con confianza no reconocida.")
        if r["frp_null"] > 0:
            alerts.append(f"{tag}: {r['frp_null']} filas con frp vacío.")

    # Deriva de la hora de paso respecto al primer año de cada sensor
    for sensor, g in files_df.dropna(subset=["day_pass_median_min"]).groupby("sensor"):
        g = g.sort_values("year")
        base = g.iloc[0]
        for _, r in g.iloc[1:].iterrows():
            shift = r["day_pass_median_min"] - base["day_pass_median_min"]
            if abs(shift) >= MAX_PASS_SHIFT_MIN:
                alerts.append(f"{sensor} {int(r['year'])}: hora de paso diurna {shift:+.0f} min "
                              f"vs. {int(base['year'])} (posible deriva de órbita).")

    # Años faltantes en la secuencia de cada sensor
    for sensor, g in files_df.groupby("sensor"):
        ys = sorted(g["year"].unique())
        gap_years = sorted(set(range(ys[0], ys[-1] + 1)) - set(ys))
        if gap_years:
            alerts.append(f"{sensor}: faltan los años {gap_years} entre {ys[0]} y {ys[-1]}.")

    # Quiebres en Terra/Aqua
    if "Terra/Aqua" in ratios.columns:
        s = ratios["Terra/Aqua"].dropna()
        change = s.pct_change().abs()
        for year, val in change[change > MAX_YOY_RATIO_CHANGE].items():
            alerts.append(f"Terra/Aqua cambia {100 * val:.0f} % en {year} (revisar estabilidad de Terra).")

    print("\n=== ALERTAS AUTOMÁTICAS ===")
    print("\n".join(f"  - {a}" for a in alerts) if alerts else "  Sin alertas.")


def make_plots(files_df: pd.DataFrame, annual: pd.DataFrame, out_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib no instalado: se omiten los gráficos)")
        return

    fig, ax = plt.subplots(figsize=(9, 4.5))
    for sensor in annual.columns:
        ax.plot(annual.index, annual[sensor].replace(0, np.nan), marker="o", label=sensor)
    ax.set_yscale("log")
    ax.set_title("Detecciones limpias por año (escala log)")
    ax.set_xlabel("Año")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "audit_annual_counts.png", dpi=140)
    plt.close(fig)

    g = files_df.dropna(subset=["day_pass_median_min"])
    if not g.empty:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        for sensor, s in g.groupby("sensor"):
            ax.plot(s["year"], s["day_pass_median_min"] / 60, marker="o", label=sensor)
        ax.set_title("Hora local mediana de las detecciones diurnas (deriva de órbita)")
        ax.set_xlabel("Año")
        ax.set_ylabel("Hora local")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / "audit_pass_time.png", dpi=140)
        plt.close(fig)


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["audit", "build"])
    parser.add_argument("--modis-dir", help=f"carpeta de MODIS (por defecto {MODIS_DIR})")
    parser.add_argument("--snpp-dir", help=f"carpeta de S-NPP (por defecto {SNPP_DIR})")
    parser.add_argument("--noaa20-dir", help=f"carpeta de NOAA-20 (por defecto {NOAA20_DIR}; opcional)")
    parser.add_argument("--noaa21-dir", help=f"carpeta de NOAA-21 (por defecto {NOAA21_DIR}; opcional)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help=f"carpeta de salida (por defecto {DEFAULT_OUT_DIR})")
    parser.add_argument("--years", type=int, nargs="+",
                        help="usar solo estos años (ignora el rango del script)")
    parser.add_argument("--all-years", action="store_true",
                        help="ignorar el rango YEAR_MIN-YEAR_MAX y usar todos los archivos")
    args = parser.parse_args()

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
    out_dir = Path(args.out_dir)
    if args.command == "audit":
        run_audit(files, out_dir)
    else:
        run_build(files, out_dir)


if __name__ == "__main__":
    main()
