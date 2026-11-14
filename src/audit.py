"""
Módulo de auditoría de calidad de datos FIRMS.
Cálculo de estadísticas de cobertura, métricas de paso de órbita, razones entre sensores y gráficos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    MAX_GAP_DAYS,
    MAX_LOW_CONF_PCT,
    MAX_PASS_SHIFT_MIN,
    MAX_YOY_RATIO_CHANGE,
    PERU_BBOX,
)
from io_firms import load


def hhmm(minutes: float) -> str:
    """Convierte minutos del día a cadena HH:MM."""
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


def build_ratios(annual: pd.DataFrame) -> pd.DataFrame:
    """Calcula razones anuales de conteos limpios entre pares de sensores."""
    pairs = [("Terra", "Aqua"), ("SNPP", "Aqua"), ("NOAA20", "SNPP"), ("NOAA20", "Aqua")]
    out = pd.DataFrame(index=annual.index)
    for num, den in pairs:
        if num in annual.columns and den in annual.columns:
            ratio = annual[num].replace(0, np.nan) / annual[den].replace(0, np.nan)
            out[f"{num}/{den}"] = ratio.round(3)
    return out.dropna(how="all")


def print_report(files_df: pd.DataFrame, annual: pd.DataFrame, ratios: pd.DataFrame) -> None:
    """Imprime el resumen de auditoría en consola."""
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
    """Evalúa umbrales y emite alertas automáticas sobre anomalías detectadas."""
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
    """Genera gráficos de tendencias anuales y hora de paso."""
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


def run_audit(files: list[dict], out_dir: Path) -> None:
    """Ejecuta el pipeline completo de auditoría y genera reportes."""
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
