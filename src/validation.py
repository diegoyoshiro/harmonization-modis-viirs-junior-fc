"""
Módulo de validación de la calibración MODIS Aqua -> VIIRS.

Aplica los factores calibrados (calibration.py, ventana 2012-2017) a Aqua en años retenidos y
compara la predicción con lo que VIIRS observó de verdad. Se valida contra dos satélites VIIRS
por separado:

    * S-NPP: el mismo sensor con el que se calibró (validación propiamente dicha).
    * NOAA-20: un VIIRS independiente que no entró al GLM (control externo, desde 2018).
      Si el factor es correcto, el error contra NOAA-20 debe ser parecido al de S-NPP.

Salidas principales:
    * validate_glm: métricas totales y por año contra S-NPP (base de select_model).
    * validate_by_year: una fila por año x satélite VIIRS x modelo x métrica.
      Incluye 2023-2024 marcados como "deriva_aqua" (fuera de la ventana: Aqua pasa más tarde).
    * validate_monthly: error total por mes del año.
    * viirs_consistency: razón anual NOAA-20/S-NPP.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from calibration import REF_SENSOR, TARGET_SENSOR, paired_weeks, predict_target

# Satélites VIIRS contra los que se compara la predicción por año.
VALIDATION_TARGETS = ("SNPP", "NOAA20")
# Años posteriores a la ventana de validación: se reportan aparte porque Aqua deriva desde 2023.
DRIFT_YEARS = [2023, 2024]


def _metrics(p: pd.DataFrame) -> dict:
    err = p["pred"] - p["target"]
    obs_total = p["target"].sum()
    return {
        "n_weeks": len(p),
        "obs_total": float(obs_total), "pred_total": float(p["pred"].sum()),
        "error_total_pct": float(100 * err.sum() / obs_total) if obs_total else np.nan,
        "corr": float(np.corrcoef(p["pred"], p["target"])[0, 1]) if len(p) > 1 else np.nan,
        "mae": float(err.abs().mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "mae_rel_pct": float(100 * err.abs().mean() / p["target"].mean()) if p["target"].mean() else np.nan,
        "coverage_ic_pct": float(100 * p["target"].between(p["pred_inf"], p["pred_sup"]).mean()),
    }


def validate_glm(factors: pd.DataFrame, df_weekly: pd.DataFrame, validation_years: list[int],
                 ref: str = REF_SENSOR, target: str = TARGET_SENSOR) -> pd.DataFrame:
    """
    Evalúa cada modelo/métrica aplicando el factor a `ref` en años retenidos y comparando con `target`.

    Entradas:
        factors: tabla de factores (train_glm_weekly(...)["factors"] o calibration_factors.csv).
        df_weekly: tabla `weekly_sensor`.
        validation_years: lista explícita de años ISO retenidos.
    Salidas:
        DataFrame (model, metric, period, n_weeks, obs_total, pred_total, error_total_pct, corr,
        mae, rmse, mae_rel_pct, coverage_ic_pct). period = "total" o el año.
        coverage_ic_pct mide la cobertura de la banda del factor (no es un intervalo de predicción).
    """
    rows = []
    for (model, metric), _ in factors.groupby(["model", "metric"]):
        pairs = paired_weeks(df_weekly, validation_years, metric, ref, target)
        pred = predict_target(pairs, factors, model, metric)
        rows.append({"model": model, "metric": metric, "period": "total", **_metrics(pred)})
        for year, g in pred.groupby("iso_year"):
            rows.append({"model": model, "metric": metric, "period": str(year), **_metrics(g)})
    return pd.DataFrame(rows)


def validate_by_year(factors: pd.DataFrame, df_weekly: pd.DataFrame, validation_years: list[int],
                     extra_years: list[int] | None = None,
                     targets: tuple[str, ...] = VALIDATION_TARGETS, ref: str = REF_SENSOR) -> pd.DataFrame:
    """
    Validación año a año contra cada satélite VIIRS (S-NPP y NOAA-20).

    Para cada satélite se usan solo las semanas en que ese satélite tiene datos completos
    (>= MIN_TARGET_DAYS días) y no hay apagón documentado de Aqua ni de él. Por eso el número de
    semanas puede diferir entre S-NPP y NOAA-20 (p. ej. 2022, por el apagón de S-NPP).

    Salidas:
        DataFrame (target, ventana, year, model, metric, n_weeks, obs_total, pred_total,
        error_total_pct, corr, mae, rmse, mae_rel_pct, coverage_ic_pct).
        ventana = "validacion" para validation_years y "deriva_aqua" para extra_years.
    """
    extra_years = [y for y in (extra_years or []) if y not in validation_years]
    years = list(validation_years) + extra_years
    sensors = set(df_weekly["sensor"].unique())
    rows = []
    for target in targets:
        if target not in sensors:
            print(f"Aviso: {target} no está en la tabla semanal; se omite en la validación por año.")
            continue
        for (model, metric), _ in factors.groupby(["model", "metric"]):
            pairs = paired_weeks(df_weekly, years, metric, ref, target)
            if pairs.empty:
                continue
            pred = predict_target(pairs, factors, model, metric)
            for year, g in pred.groupby("iso_year"):
                ventana = "validacion" if year in validation_years else "deriva_aqua"
                rows.append({"target": target, "ventana": ventana, "year": int(year),
                             "model": model, "metric": metric, **_metrics(g)})
    return pd.DataFrame(rows)


def validate_monthly(factors: pd.DataFrame, df_weekly: pd.DataFrame, validation_years: list[int],
                     ref: str = REF_SENSOR, target: str = TARGET_SENSOR) -> pd.DataFrame:
    """Error total por mes del año (estacionalidad del sesgo) para cada modelo y métrica."""
    rows = []
    for (model, metric), _ in factors.groupby(["model", "metric"]):
        pairs = paired_weeks(df_weekly, validation_years, metric, ref, target)
        pred = predict_target(pairs, factors, model, metric)
        for month, g in pred.groupby("month"):
            obs = g["target"].sum()
            rows.append({"model": model, "metric": metric, "month": int(month),
                         "obs_total": float(obs), "pred_total": float(g["pred"].sum()),
                         "error_total_pct": float(100 * (g["pred"].sum() - obs) / obs) if obs else np.nan})
    return pd.DataFrame(rows)


def viirs_consistency(df_weekly: pd.DataFrame, years: list[int],
                      a: str = "NOAA20", b: str = "SNPP") -> pd.DataFrame:
    """Control: razón anual NOAA-20/S-NPP (debería ser ~1 si VIIRS es una serie unificada)."""
    d = df_weekly[df_weekly["sensor"].isin([a, b]) & df_weekly["iso_year"].isin(years)]
    t = d.pivot_table(index="iso_year", columns="sensor", values="count", aggfunc="sum")
    if a not in t or b not in t:
        return pd.DataFrame()
    t[f"{a}/{b}"] = (t[a] / t[b]).round(3)
    return t.reset_index()


def plot_validation(df_weekly: pd.DataFrame, factors: pd.DataFrame, model: str, years: list[int],
                    path: Path, ref: str = REF_SENSOR, target: str = TARGET_SENSOR) -> None:
    """Serie semanal observada vs predicha y diagrama de dispersión (conteos)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pairs = paired_weeks(df_weekly, years, "count", ref, target)
    p = predict_target(pairs, factors, model, "count")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 4.5), gridspec_kw={"width_ratios": [3, 1]})
    ax1.fill_between(p["week"], p["pred_inf"], p["pred_sup"], color="tab:blue", alpha=0.25,
                     label="banda IC 95 % del factor")
    ax1.plot(p["week"], p["target"], color="tab:orange", lw=1.2, label=f"{target} observado")
    ax1.plot(p["week"], p["pred"], color="tab:blue", lw=1.2, label=f"{ref} × factor (modelo {model})")
    ax1.set_title(f"Validación semanal {years[0]}-{years[-1]} (conteo limpio, todo el dominio)")
    ax1.set_ylabel("detecciones por semana")
    ax1.legend()
    lim = max(p["target"].max(), p["pred"].max()) * 1.05
    ax2.scatter(p["target"], p["pred"], s=8, alpha=0.6)
    ax2.plot([0, lim], [0, lim], color="gray", lw=1, ls="--")
    ax2.set_xlim(0, lim)
    ax2.set_ylim(0, lim)
    ax2.set_xlabel(f"{target} observado")
    ax2.set_ylabel("predicción")
    ax2.set_title("Predicción vs observado")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def run_validation(factors: pd.DataFrame, df_weekly: pd.DataFrame, validation_years: list[int],
                   out_dir: Path, plot_dir: Path | None = None, model_for_plot: str | None = None,
                   extra_years: list[int] | None = None) -> dict:
    """
    Paso 5 del explainer: valida los factores calibrados en años retenidos.

    Guarda en out_dir: validation_metrics.csv (contra S-NPP), validation_by_year.csv (S-NPP y
    NOAA-20, año a año), validation_monthly.csv y validation_noaa20_snpp.csv.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    extra_years = DRIFT_YEARS if extra_years is None else extra_years

    print(f"\nValidación {validation_years[0]}-{validation_years[-1]} ({REF_SENSOR} × factor vs {TARGET_SENSOR})")
    validation = validate_glm(factors, df_weekly, validation_years)
    validation.to_csv(out_dir / "validation_metrics.csv", index=False)
    cols = ["model", "metric", "period", "n_weeks", "error_total_pct", "corr", "mae", "mae_rel_pct", "coverage_ic_pct"]
    print(validation[validation["period"] == "total"][cols].round(3).to_string(index=False))

    by_year = validate_by_year(factors, df_weekly, validation_years, extra_years)
    by_year.to_csv(out_dir / "validation_by_year.csv", index=False)
    if not by_year.empty:
        print("\nValidación por año contra S-NPP y NOAA-20 (conteos; error % = predicho vs observado):")
        cnt = by_year[by_year["metric"] == "count"]
        table = cnt.pivot_table(index=["ventana", "year"], columns=["model", "target"],
                                values="error_total_pct").round(1)
        print(table.to_string())

    monthly = validate_monthly(factors, df_weekly, validation_years)
    monthly.to_csv(out_dir / "validation_monthly.csv", index=False)

    control = viirs_consistency(df_weekly, validation_years + [y for y in extra_years if y not in validation_years])
    if not control.empty:
        control.to_csv(out_dir / "validation_noaa20_snpp.csv", index=False)
        print("\nControl NOAA-20/S-NPP (debería ser ~1):")
        print(control.to_string(index=False))

    if plot_dir is not None and model_for_plot is not None:
        plot_dir.mkdir(parents=True, exist_ok=True)
        plot_validation(df_weekly, factors, model_for_plot, validation_years,
                        plot_dir / "calibration_validation.png")

    return {"validation": validation, "by_year": by_year, "monthly": monthly, "control": control}
