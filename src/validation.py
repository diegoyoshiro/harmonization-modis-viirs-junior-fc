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


# ---------------------------------------------------------------------------
# Predicción MODIS (Aqua × factor) hasta el último año y comparación con S-NPP
# ---------------------------------------------------------------------------
PERIODS = {
    "2012-2017 calibración": (2012, 2017),
    "2018-2022 validación": (2018, 2022),
    "2023-2024 fuera de ventana (deriva Aqua)": (2023, 2024),
}


def predict_vs_viirs(df_weekly: pd.DataFrame, factors: pd.DataFrame, model: str, years: list[int],
                     bands: pd.DataFrame | None = None, metric: str = "count",
                     target: str = TARGET_SENSOR) -> pd.DataFrame:
    """
    Aqua × factor semana a semana en `years`, emparejado con el VIIRS observado (`target`).
    Si se pasan `bands` (harmonization_bands.csv), agrega band_inf/band_sup (banda de predicción).
    """
    pairs = paired_weeks(df_weekly, years, metric, REF_SENSOR, target)
    p = predict_target(pairs, factors, model, metric)
    if bands is not None:
        out_name = "count" if metric == "count" else "frp"
        q = bands[bands["metric"] == out_name].set_index("season")
        p["band_inf"] = p["pred"] * p["season"].map(q["q_inf"])
        p["band_sup"] = p["pred"] * p["season"].map(q["q_sup"])
    return p


def _period_metrics(p: pd.DataFrame, label: str) -> dict:
    m = _metrics(p)
    if "band_inf" in p:
        m["coverage_band90_pct"] = float(100 * p["target"].between(p["band_inf"], p["band_sup"]).mean())
    tot = p.groupby("iso_year")[["target", "pred"]].sum()
    err_year = 100 * (tot["pred"] - tot["target"]) / tot["target"]
    m["max_abs_error_anual_pct"] = float(err_year.abs().max())
    return {"periodo": label, **m}


def prediction_report(df_weekly: pd.DataFrame, final_factors: pd.DataFrame, calibration_factors: pd.DataFrame,
                      model: str, bands: pd.DataFrame, out_dir: Path, plot_dir: Path | None = None,
                      last_year: int = 2024) -> dict:
    """
    Predice con MODIS Aqua × factor desde 2002 hasta last_year y lo compara con S-NPP (2012-last_year).

    Dos juegos de factores:
        * final (2012-2022): el que usa la serie única. En 2012-2022 es en muestra; 2023-2024 no.
        * calibración (2012-2017): prueba honesta, fuera de muestra desde 2018.
    Guarda prediction_vs_snpp_weekly.csv, prediction_vs_snpp_annual.csv, prediction_vs_snpp_metrics.csv
    y output/reports/prediction_vs_snpp.png.
    """
    sets = {"final 2012-2022": final_factors[final_factors["model"] == model],
            "calibración 2012-2017": calibration_factors[calibration_factors["model"] == model]}
    years = list(range(2012, last_year + 1))
    weekly, annual, metrics = [], [], []
    for name, f in sets.items():
        for metric in ("count", "total_frp"):
            p = predict_vs_viirs(df_weekly, f, model, years, bands, metric)
            p = p.assign(factores=name, metric=metric)
            weekly.append(p)
            tot = p.groupby("iso_year")[["target", "pred"]].sum().reset_index()
            tot["error_pct"] = 100 * (tot["pred"] - tot["target"]) / tot["target"]
            annual.append(tot.assign(factores=name, metric=metric))
            for label, (lo, hi) in PERIODS.items():
                g = p[p["iso_year"].between(lo, hi)]
                if len(g) > 1:
                    metrics.append({"factores": name, "metric": metric, **_period_metrics(g, label)})
            metrics.append({"factores": name, "metric": metric, **_period_metrics(p, f"2012-{last_year} total")})
    weekly = pd.concat(weekly, ignore_index=True).rename(columns={"ref": "aqua", "target": "snpp"})
    annual = pd.concat(annual, ignore_index=True).rename(columns={"target": "snpp"})
    metrics = pd.DataFrame(metrics)
    weekly.to_csv(out_dir / "prediction_vs_snpp_weekly.csv", index=False)
    annual.to_csv(out_dir / "prediction_vs_snpp_annual.csv", index=False)
    metrics.to_csv(out_dir / "prediction_vs_snpp_metrics.csv", index=False)

    cols = ["factores", "metric", "periodo", "n_weeks", "error_total_pct", "corr", "mae_rel_pct",
            "coverage_band90_pct", "max_abs_error_anual_pct"]
    print("\nPredicción MODIS (Aqua × factor) vs S-NPP observado:")
    print(metrics[cols].round(2).to_string(index=False))

    if plot_dir is not None:
        # Predicción completa 2002-last_year (sin emparejar) para el panel superior
        full = df_weekly[(df_weekly["sensor"] == REF_SENSOR) & df_weekly["iso_year"].between(2002, last_year)
                         & (df_weekly["days_with_data"] > 0)]
        full = predict_target(full.rename(columns={"count": "ref"}), sets["final 2012-2022"], model, "count")
        plot_prediction(full, weekly, annual, metrics, bands, plot_dir / "prediction_vs_snpp.png", last_year)
    return {"weekly": weekly, "annual": annual, "metrics": metrics}


def plot_prediction(full: pd.DataFrame, weekly: pd.DataFrame, annual: pd.DataFrame, metrics: pd.DataFrame,
                    bands: pd.DataFrame, path: Path, last_year: int) -> None:
    """Figura de 5 paneles: serie semanal, totales anuales, dispersión, error anual y tabla de métricas."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c_pred, c_obs = "tab:blue", "tab:orange"
    fig = plt.figure(figsize=(16, 13))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.1, 1, 1], width_ratios=[1.6, 1])

    # 1) Serie semanal 2002-last_year: predicción MODIS y S-NPP observado
    ax = fig.add_subplot(gs[0, :])
    q = bands[bands["metric"] == "count"].set_index("season")
    full = full.sort_values("week")
    ax.fill_between(full["week"], full["pred"] * full["season"].map(q["q_inf"]),
                    full["pred"] * full["season"].map(q["q_sup"]), color=c_pred, alpha=0.18, lw=0,
                    label="banda de predicción 90 %")
    ax.plot(full["week"], full["pred"], color=c_pred, lw=0.9, label="predicción MODIS Aqua × factor")
    w = weekly[(weekly["factores"] == "final 2012-2022") & (weekly["metric"] == "count")].sort_values("week")
    ax.plot(w["week"], w["snpp"], color=c_obs, lw=0.9, alpha=0.9, label="VIIRS S-NPP observado")
    ax.axvspan(pd.Timestamp("2012-01-01"), pd.Timestamp("2023-01-01"), color="0.85", alpha=0.35, lw=0)
    ax.axvspan(pd.Timestamp("2023-01-01"), pd.Timestamp(f"{last_year + 1}-01-01"), color="tab:red",
               alpha=0.08, lw=0)
    ymax = max(full["pred"].max(), w["snpp"].max())
    ax.set_ylim(0, ymax * 1.08)
    ax.text(pd.Timestamp("2007-01-01"), ymax * 1.02, "solo MODIS (sin VIIRS para comparar)", ha="center", fontsize=9)
    ax.text(pd.Timestamp("2017-07-01"), ymax * 1.02, "ventana del factor final (2012-2022)", ha="center", fontsize=9)
    ax.text(pd.Timestamp("2024-01-01"), ymax * 1.02, "fuera de muestra", ha="center", fontsize=9)
    ax.set_title(f"Predicción con MODIS (Aqua × factor por temporada, modelo B) vs VIIRS S-NPP, Perú 2002-{last_year}")
    ax.set_ylabel("focos por semana")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 0.93), fontsize=8)

    # 2) Totales anuales
    ax = fig.add_subplot(gs[1, 0])
    a = annual[(annual["factores"] == "final 2012-2022") & (annual["metric"] == "count")]
    x = np.arange(len(a))
    ax.bar(x - 0.2, a["snpp"], 0.4, color=c_obs, label="S-NPP observado")
    ax.bar(x + 0.2, a["pred"], 0.4, color=c_pred, label="MODIS × factor")
    for xi, (_, r) in zip(x, a.iterrows()):
        ax.text(xi, max(r["snpp"], r["pred"]) * 1.01, f"{r['error_pct']:+.1f}%", ha="center", fontsize=8,
                color="tab:red" if abs(r["error_pct"]) > 5 else "k")
    ax.set_xticks(x)
    ax.set_xticklabels(a["iso_year"], rotation=45)
    ax.set_ylim(0, max(a["snpp"].max(), a["pred"].max()) * 1.15)
    ax.set_ylabel("focos por año (semanas comparables)")
    ax.set_title("Total anual: error de la predicción (factor final)")
    ax.legend(fontsize=8, loc="upper left")

    # 3) Dispersión semanal en escala log
    ax = fig.add_subplot(gs[1, 1])
    colors = {"alta": "tab:red", "media": "tab:olive", "baja": "tab:cyan"}
    for season, g in w.groupby("season"):
        ax.scatter(g["snpp"].clip(lower=1), g["pred"].clip(lower=1), s=7, alpha=0.6,
                   color=colors.get(season), label=f"temporada {season}")
    lim = [1, max(w["snpp"].max(), w["pred"].max()) * 1.3]
    ax.plot(lim, lim, color="k", lw=1, ls="--")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("S-NPP observado (focos/semana)")
    ax.set_ylabel("MODIS × factor")
    m = metrics[(metrics["factores"] == "final 2012-2022") & (metrics["metric"] == "count")
                & metrics["periodo"].str.endswith("total")].iloc[0]
    ax.set_title(f"Semanal 2012-{last_year}: r = {m['corr']:.3f}, MAE rel. = {m['mae_rel_pct']:.0f} %")
    ax.legend(fontsize=8, loc="upper left")

    # 4) Error anual por juego de factores (conteo y FRP)
    ax = fig.add_subplot(gs[2, 0])
    styles = {("final 2012-2022", "count"): ("tab:blue", "-", "o"),
              ("calibración 2012-2017", "count"): ("tab:blue", "--", "s"),
              ("final 2012-2022", "total_frp"): ("tab:purple", "-", "o"),
              ("calibración 2012-2017", "total_frp"): ("tab:purple", "--", "s")}
    for (fname, metric), (color, ls, mk) in styles.items():
        g = annual[(annual["factores"] == fname) & (annual["metric"] == metric)]
        ax.plot(g["iso_year"], g["error_pct"], color=color, ls=ls, marker=mk, ms=4,
                label=f"{'conteo' if metric == 'count' else 'FRP'} · factores {fname}")
    ax.axhspan(-5, 5, color="tab:green", alpha=0.1, lw=0)
    ax.axhline(0, color="k", lw=0.8)
    ax.axvline(2017.5, color="0.4", ls=":", lw=1)
    ax.axvline(2022.5, color="0.4", ls=":", lw=1)
    ax.set_xticks(sorted(annual["iso_year"].unique()))
    ax.set_ylabel("error anual (%)  (+ = sobreestima)")
    ax.set_title("Error anual vs S-NPP (franja verde = ±5 %)")
    ax.legend(fontsize=7, ncol=2, loc="upper left")

    # 5) Tabla de métricas (conteo)
    ax = fig.add_subplot(gs[2, 1])
    ax.axis("off")
    t = metrics[metrics["metric"] == "count"]
    short = {"calibración": "calib.", "validación": "valid.", "fuera de ventana (deriva Aqua)": "deriva"}

    def _short(label: str) -> str:
        years, _, rest = label.partition(" ")
        lo, hi = years.split("-")
        return f"{lo}-{hi[2:]} {short.get(rest, rest)}"

    rows = [[r["factores"].split()[0], _short(r["periodo"]),
             f"{r['error_total_pct']:+.1f}", f"{r['corr']:.3f}", f"{r['mae_rel_pct']:.0f}",
             f"{r['coverage_band90_pct']:.0f}"] for _, r in t.iterrows()]
    tab = ax.table(cellText=rows, colLabels=["factores", "período", "error total %", "r", "MAE rel. %",
                                             "en banda 90 %"], loc="center", cellLoc="center")
    tab.auto_set_font_size(False)
    tab.set_fontsize(8)
    tab.scale(1, 1.35)
    ax.set_title("Precisión semanal del conteo (vs S-NPP)", fontsize=10)

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
