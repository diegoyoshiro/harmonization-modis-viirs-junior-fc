"""
Módulo de calibración empírica MODIS Aqua -> VIIRS S-NPP.

La validación en años retenidos (S-NPP y NOAA-20, año a año) está en validation.py.

Ajusta GLM semanales sobre la tabla larga `weekly_sensor` (semana x sensor, todo el dominio):

    y ~ C(week_id) + viirs                 Modelo A: un solo factor
    y ~ C(week_id) + viirs:C(season)       Modelo B: un factor por temporada

El efecto fijo de semana absorbe la actividad real de fuego de cada semana; el coeficiente de
`viirs` es log(VIIRS/Aqua), así que el factor de armonización es exp(beta).

- Conteos: familia Poisson. Totales de FRP: Tweedie (var_power=1.5, enlace log), que admite ceros.
- Errores estándar agrupados por semana (cluster-robust): son válidos aunque haya sobredispersión,
  por eso no hace falta pasar a binomial negativa para la inferencia del factor. La dispersión de
  Pearson se reporta igualmente como diagnóstico.
- Semanas excluidas:
    * Aqua sin observaciones (days_with_data == 0). No se exige más: en temporada baja Aqua tiene
      pocos días con detecciones porque no hay fuego, y filtrarlas sesgaría la razón.
    * VIIRS con days_with_data < MIN_TARGET_DAYS. VIIRS detecta algo en Perú casi todos los días,
      así que una semana incompleta es un apagón del satélite (p. ej. S-NPP jul-ago 2022).
    * Semanas que se solapan con un apagón documentado de cualquiera de los dos sensores
      (columna in_outage, definida en settings.yaml -> outages; p. ej. Aqua ago-sep 2020).
    * Semanas en que ambos sensores suman 0 (no aportan información sobre la razón).
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REF_SENSOR = "Aqua"
TARGET_SENSOR = "SNPP"
METRIC_FAMILIES = {"count": "poisson", "total_frp": "tweedie"}
MODEL_FORMULAS = {
    "A": "y ~ C(week_id) + viirs",
    "B": "y ~ C(week_id) + viirs:C(season)",
}
# Días mínimos con datos del sensor objetivo (VIIRS) para aceptar una semana.
MIN_TARGET_DAYS = 6
# Un modelo más complejo solo se elige si mejora el MAE de validación en más de este porcentaje.
MIN_IMPROVEMENT_PCT = 5.0


def years_from_window(window: list[int]) -> list[int]:
    """Convierte una ventana [inicio, fin] de settings.yaml en la lista de años (fin inclusivo)."""
    lo, hi = int(window[0]), int(window[-1])
    return list(range(lo, hi + 1))


def paired_weeks(df_weekly: pd.DataFrame, years: list[int], metric: str,
                 ref: str = REF_SENSOR, target: str = TARGET_SENSOR) -> pd.DataFrame:
    """
    Tabla ancha con una fila por semana válida: week, iso_year, month, season, ref, target.
    Válida = ref con alguna observación y target con >= MIN_TARGET_DAYS días con datos.
    """
    d = df_weekly[df_weekly["sensor"].isin([ref, target]) & df_weekly["iso_year"].isin(years)]
    min_days = d["sensor"].map({ref: 1, target: MIN_TARGET_DAYS})
    d = d[d["days_with_data"] >= min_days]
    if "in_outage" in d.columns:
        # Una semana con apagón documentado de cualquiera de los dos sensores se descarta entera.
        bad_weeks = d.loc[d["in_outage"], "week"].unique()
        d = d[~d["week"].isin(bad_weeks)]
    wide = d.pivot_table(index=["week", "iso_year", "month", "season"], columns="sensor",
                         values=metric, aggfunc="sum").dropna(subset=[ref, target])
    wide = wide.reset_index()
    wide.columns.name = None
    return wide.rename(columns={ref: "ref", target: "target"})


def _long_for_glm(pairs: pd.DataFrame) -> pd.DataFrame:
    """Pasa la tabla ancha a formato largo (2 filas por semana) y quita semanas con 0 en ambos."""
    pairs = pairs[(pairs["ref"] + pairs["target"]) > 0]
    base = pairs[["week", "season"]].assign(week_id=pairs["week"].dt.strftime("%Y-%m-%d"))
    long = pd.concat([
        base.assign(viirs=0, y=pairs["ref"].to_numpy()),
        base.assign(viirs=1, y=pairs["target"].to_numpy()),
    ], ignore_index=True)
    return long


def _family(name: str):
    import statsmodels.api as sm
    if name == "poisson":
        return sm.families.Poisson()
    return sm.families.Tweedie(var_power=1.5, link=sm.families.links.Log())


def _fit(formula: str, data: pd.DataFrame, family: str):
    import statsmodels.formula.api as smf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # avisos de convergencia por efectos fijos de semanas pequeñas
        return smf.glm(formula, data=data, family=_family(family)).fit(
            cov_type="cluster", cov_kwds={"groups": pd.factorize(data["week_id"])[0]})


def _factor_rows(result, model: str, metric: str, seasons: list[str]) -> list[dict]:
    """Extrae exp(beta) e IC 95 % de los coeficientes de viirs."""
    ci = result.conf_int()
    rows = []
    for name in result.params.index:
        if "viirs" not in name:
            continue
        season = "todas"
        for s in seasons:
            if f"[{s}]" in name or f"[T.{s}]" in name:
                season = s
        beta = result.params[name]
        rows.append({
            "model": model, "metric": metric, "season": season,
            "factor": float(np.exp(beta)),
            "ic_inf": float(np.exp(ci.loc[name, 0])), "ic_sup": float(np.exp(ci.loc[name, 1])),
            "beta": float(beta), "se": float(result.bse[name]),
        })
    return rows


def train_glm_weekly(df_weekly: pd.DataFrame, calibration_years: list[int],
                     metrics: tuple[str, ...] = ("count", "total_frp"),
                     models: tuple[str, ...] = ("A", "B"),
                     ref: str = REF_SENSOR, target: str = TARGET_SENSOR) -> dict:
    """
    Calibra los GLM semanales entre `ref` (Aqua) y `target` (S-NPP).

    Entradas:
        df_weekly: tabla `weekly_sensor` (aggregate.aggregate_weekly(level="national")).
        calibration_years: lista explícita de años ISO (usar years_from_window para una ventana).
    Salidas:
        dict con ref, target, years, factors (DataFrame: model, metric, season, factor, ic_inf,
        ic_sup, beta, se, n_weeks, dispersion, aic) y diagnostics por modelo.
    """
    rows, diagnostics = [], {}
    for metric in metrics:
        pairs = paired_weeks(df_weekly, calibration_years, metric, ref, target)
        long = _long_for_glm(pairs)
        seasons = sorted(long["season"].unique())
        for model in models:
            res = _fit(MODEL_FORMULAS[model], long, METRIC_FAMILIES[metric])
            dispersion = float(res.pearson_chi2 / res.df_resid) if res.df_resid > 0 else np.nan
            n_weeks = int(long["week_id"].nunique())
            for r in _factor_rows(res, model, metric, seasons):
                r["n_weeks"] = int(long.loc[long["season"].eq(r["season"]) | (r["season"] == "todas"),
                                            "week_id"].nunique())
                r["dispersion"] = dispersion
                r["aic"] = float(res.aic)
                rows.append(r)
            diagnostics[f"{model}_{metric}"] = {
                "formula": MODEL_FORMULAS[model], "family": METRIC_FAMILIES[metric],
                "n_obs": int(res.nobs), "n_weeks": n_weeks,
                "pearson_dispersion": dispersion, "aic": float(res.aic),
                "converged": bool(res.converged),
            }
    return {
        "ref": ref, "target": target, "years": list(calibration_years),
        "factors": pd.DataFrame(rows), "diagnostics": diagnostics,
    }


def _factor_lookup(factors: pd.DataFrame, model: str, metric: str) -> dict[str, pd.Series]:
    sub = factors[(factors["model"] == model) & (factors["metric"] == metric)]
    return {row["season"]: row for _, row in sub.iterrows()}


def predict_target(pairs: pd.DataFrame, factors: pd.DataFrame, model: str, metric: str) -> pd.DataFrame:
    """Aplica el factor (por temporada si el modelo lo tiene) a la serie de referencia."""
    lookup = _factor_lookup(factors, model, metric)
    if "todas" in lookup:
        f = pd.DataFrame([lookup["todas"]] * len(pairs), index=pairs.index)
    else:
        f = pd.DataFrame([lookup[s] for s in pairs["season"]], index=pairs.index)
    out = pairs.copy()
    out["pred"] = out["ref"] * f["factor"].astype(float)
    out["pred_inf"] = out["ref"] * f["ic_inf"].astype(float)
    out["pred_sup"] = out["ref"] * f["ic_sup"].astype(float)
    return out


def select_model(validation: pd.DataFrame, metric: str = "count") -> str:
    """Elige el modelo más simple salvo que uno más complejo mejore el MAE en > MIN_IMPROVEMENT_PCT."""
    v = validation[(validation["metric"] == metric) & (validation["period"] == "total")]
    v = v.set_index("model").sort_index()  # A, B, ... = de menos a más complejo
    chosen = v.index[0]
    for model in v.index[1:]:
        if v.loc[model, "mae"] < v.loc[chosen, "mae"] * (1 - MIN_IMPROVEMENT_PCT / 100):
            chosen = model
    return chosen


def run_calibration(df_weekly: pd.DataFrame, calibration_years: list[int], validation_years: list[int],
                    final_years: list[int], out_dir: Path, plot_dir: Path | None = None) -> dict:
    """
    Pasos 4-6 del explainer: calibrar A/B, validar en años retenidos (módulo validation), elegir
    el modelo y reajustarlo con todos los años estables para obtener el factor definitivo con IC 95 %.
    """
    # Import local: validation.py importa paired_weeks/predict_target de este módulo.
    from validation import plot_validation, run_validation

    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)

    print(f"Calibración {calibration_years[0]}-{calibration_years[-1]} "
          f"({REF_SENSOR} -> {TARGET_SENSOR}, tabla semanal nacional)")
    fit = train_glm_weekly(df_weekly, calibration_years)
    fit["factors"].to_csv(out_dir / "calibration_factors.csv", index=False)
    print(fit["factors"][["model", "metric", "season", "factor", "ic_inf", "ic_sup", "n_weeks", "dispersion"]]
          .round(3).to_string(index=False))

    val = run_validation(fit["factors"], df_weekly, validation_years, out_dir)
    validation = val["validation"]

    chosen = select_model(validation, "count")
    print(f"\nModelo elegido para conteos: {chosen} "
          f"(el más simple salvo mejora de MAE > {MIN_IMPROVEMENT_PCT:.0f} % en validación)")

    print(f"Reajuste final con años estables {final_years[0]}-{final_years[-1]}")
    final = train_glm_weekly(df_weekly, final_years, models=(chosen,))
    final_factors = final["factors"].assign(years=f"{final_years[0]}-{final_years[-1]}")
    final_factors.to_csv(out_dir / "harmonization_factors.csv", index=False)
    print(final_factors[["model", "metric", "season", "factor", "ic_inf", "ic_sup", "n_weeks"]]
          .round(3).to_string(index=False))

    summary = {
        "ref": REF_SENSOR, "target": TARGET_SENSOR,
        "calibration_years": calibration_years, "validation_years": validation_years,
        "final_years": final_years, "chosen_model": chosen,
        "selection_rule": f"modelo más simple salvo mejora de MAE > {MIN_IMPROVEMENT_PCT} % en validación",
        "diagnostics_calibration": fit["diagnostics"], "diagnostics_final": final["diagnostics"],
    }
    (out_dir / "calibration_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    if plot_dir is not None:
        plot_dir.mkdir(parents=True, exist_ok=True)
        plot_validation(df_weekly, fit["factors"], chosen, validation_years,
                        plot_dir / "calibration_validation.png")

    print(f"\nTablas guardadas en: {out_dir}")
    return {"fit": fit, "validation": validation, "by_year": val["by_year"], "chosen": chosen, "final": final}
