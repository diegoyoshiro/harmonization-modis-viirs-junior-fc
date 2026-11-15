"""
Módulo de armonización: serie única de actividad de quema 2002-hoy en "unidades VIIRS".

    * 2002-2011 (tramo "estimado"): Aqua × factor de temporada (harmonization_factors.csv).
      Solo se usa el factor, nunca el efecto fijo de semana del GLM.
    * 2012 en adelante (tramo "VIIRS real"): S-NPP si la semana tiene >= MIN_TARGET_DAYS días con
      datos y no hay apagón documentado; si no, NOAA-20 (y luego NOAA-21). Si ningún VIIRS sirve,
      la semana se rellena con Aqua × factor (calidad "relleno"), p. ej. enero de 2012.
    * Semanas sin dato de Aqua (0 días con detecciones en todo Perú o una falta de dato registrada en
      settings.yaml -> harmonize.aqua_gaps) quedan como NaN ("sin dato"), nunca como cero.

El factor se aplica solo a series agregadas (nación/semana o celda/semana), nunca a focos sueltos.

Incertidumbre del tramo estimado (columnas de la tabla nacional):
    * *_ic_inf / *_ic_sup: banda del IC 95 % del factor (error sistemático de la razón).
    * *_inf / *_sup: banda de predicción semanal. Cuantiles empíricos de observado/predicho en los
      años de validación (factores de calibración aplicados fuera de muestra), por temporada. Incluye
      el error del factor y el ruido semanal; el IC del factor solo cubría ~19 % de las semanas.
    * Totales anuales: banda con la razón observado/predicho anual mínima y máxima en validación
      (S-NPP y NOAA-20), porque los errores semanales se compensan dentro del año.
En VIIRS real las bandas son iguales al valor (no hay conversión).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from calibration import MIN_TARGET_DAYS, REF_SENSOR, paired_weeks, predict_target
from config import HARMONIZE

# Orden de preferencia de los satélites VIIRS para el tramo real.
VIIRS_PRIORITY = ("SNPP", "NOAA20", "NOAA21")
SOURCE_LABELS = {"SNPP": "S-NPP", "NOAA20": "NOAA-20", "NOAA21": "NOAA-21"}
# métrica de salida -> columna de las tablas semanales
METRICS = {"count": "count", "frp": "total_frp"}
CELL_KEYS = ["cell", "lat_c", "lon_c"]
CALENDAR = ["iso_year", "iso_week", "month", "season"]


# ---------------------------------------------------------------------------
# Selección de fuente por semana
# ---------------------------------------------------------------------------
def _sensor_week_status(df: pd.DataFrame) -> pd.DataFrame:
    """Días con datos (en todo el dominio) y apagón por semana × sensor. Vale para ambas tablas."""
    return (df.groupby(["week", "sensor"])
              .agg(days=("days_with_data", "max"), outage=("in_outage", "any"))
              .reset_index())


def aqua_missing_weeks(df: pd.DataFrame, gaps: list[tuple[str, str]] | None = None) -> pd.Series:
    """
    Semanas sin dato de Aqua: 0 días con detecciones en todo el dominio o solapadas con una falta
    de dato registrada (harmonize.aqua_gaps). Devuelve las fechas de lunes como Series.
    """
    gaps = HARMONIZE["aqua_gaps"] if gaps is None else gaps
    st = _sensor_week_status(df)
    aq = st[st["sensor"] == REF_SENSOR]
    missing = aq["days"].eq(0) | aq["outage"]
    week_end = aq["week"] + pd.Timedelta(days=6)
    for start, end in gaps:
        missing |= (aq["week"] <= pd.Timestamp(end)) & (week_end >= pd.Timestamp(start))
    return aq.loc[missing, "week"].reset_index(drop=True)


def choose_viirs(df: pd.DataFrame, priority: tuple[str, ...] = VIIRS_PRIORITY,
                 min_days: int = MIN_TARGET_DAYS) -> pd.DataFrame:
    """
    Satélite VIIRS a usar en cada semana: el primero de `priority` con >= min_days días con datos y
    sin apagón documentado. Devuelve (week, viirs_sensor, viirs_days); semanas sin VIIRS válido
    quedan con viirs_sensor = NaN.
    """
    st = _sensor_week_status(df)
    st = st[st["sensor"].isin(priority)]
    ok = st[(st["days"] >= min_days) & ~st["outage"]].copy()
    ok["rank"] = ok["sensor"].map({s: i for i, s in enumerate(priority)})
    best = ok.sort_values(["week", "rank"]).drop_duplicates("week")
    weeks = pd.DataFrame({"week": np.sort(st["week"].unique())})
    out = weeks.merge(best[["week", "sensor", "days"]], on="week", how="left")
    return out.rename(columns={"sensor": "viirs_sensor", "days": "viirs_days"})


def last_complete_week(df: pd.DataFrame) -> pd.Timestamp:
    """Última semana en que algún VIIRS tiene los 7 días con datos (evita la semana final parcial)."""
    st = _sensor_week_status(df)
    full = st[st["sensor"].isin(VIIRS_PRIORITY) & (st["days"] == 7)]
    return full["week"].max()


# ---------------------------------------------------------------------------
# Factores y bandas
# ---------------------------------------------------------------------------
def _factor_table(factors: pd.DataFrame) -> pd.DataFrame:
    """Factor e IC por temporada y métrica en formato ancho: season, factor_count, ic_inf_count, ..."""
    parts = []
    for out_name, col in METRICS.items():
        sub = factors[factors["metric"] == col][["season", "factor", "ic_inf", "ic_sup"]]
        parts.append(sub.set_index("season").add_suffix(f"_{out_name}"))
    table = pd.concat(parts, axis=1)
    if list(table.index) == ["todas"]:  # modelo A: un solo factor para todas las temporadas
        table = pd.concat([table.rename(index={"todas": s}) for s in ("alta", "media", "baja")])
    return table.reset_index()


def empirical_bands(df_weekly: pd.DataFrame, calibration_factors: pd.DataFrame, model: str,
                    validation_years: list[int], coverage: float | None = None) -> pd.DataFrame:
    """
    Cuantiles de observado/predicho semanales en validación (fuera de muestra), por temporada.

    Usa los factores de calibración (2012-2017) aplicados a Aqua en validation_years y compara con
    S-NPP. Devuelve (metric, season, q_inf, q_med, q_sup, n_weeks).
    """
    coverage = HARMONIZE["band_coverage"] if coverage is None else coverage
    lo, hi = (1 - coverage) / 2, 1 - (1 - coverage) / 2
    rows = []
    for out_name, col in METRICS.items():
        pairs = paired_weeks(df_weekly, validation_years, col)
        pred = predict_target(pairs, calibration_factors, model, col)
        pred = pred[pred["pred"] > 0]
        ratio = pred["target"] / pred["pred"]
        for season, r in ratio.groupby(pred["season"]):
            rows.append({"metric": out_name, "season": season, "q_inf": float(r.quantile(lo)),
                         "q_med": float(r.median()), "q_sup": float(r.quantile(hi)), "n_weeks": int(len(r))})
    return pd.DataFrame(rows)


def annual_band(df_weekly: pd.DataFrame, calibration_factors: pd.DataFrame, model: str,
                validation_years: list[int], targets: tuple[str, ...] = ("SNPP", "NOAA20")) -> pd.DataFrame:
    """Razón observado/predicho anual (mínima y máxima) en validación, por métrica."""
    rows = []
    for out_name, col in METRICS.items():
        ratios = []
        for target in targets:
            if target not in set(df_weekly["sensor"]):
                continue
            pairs = paired_weeks(df_weekly, validation_years, col, REF_SENSOR, target)
            pred = predict_target(pairs, calibration_factors, model, col)
            tot = pred.groupby("iso_year")[["target", "pred"]].sum()
            ratios.extend((tot["target"] / tot["pred"]).tolist())
        # La banda siempre incluye el valor central (razón 1). Si las razones quedan todas a un lado
        # (p. ej. FRP: el factor sobreestima ~10 %), ese sesgo queda en bias_pct para documentarlo.
        rows.append({"metric": out_name, "r_min": float(min(min(ratios), 1.0)),
                     "r_max": float(max(max(ratios), 1.0)), "r_mean": float(np.mean(ratios)),
                     "bias_pct": float(100 * (1 / np.mean(ratios) - 1)), "n_years": len(ratios)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Armonización
# ---------------------------------------------------------------------------
def apply_harmonization(df_aggregated: pd.DataFrame, model_fit: dict, target_years: list[int]) -> pd.DataFrame:
    """
    Construye la serie única semanal: Aqua × factor en target_years (y como relleno) + VIIRS real.

    Entradas:
        df_aggregated: tabla `weekly_sensor` (nacional) o `weekly_cell_sensor` (por celda). Si tiene
            columna `cell`, la salida es por celda × semana.
        model_fit: dict con "factors" (harmonization_factors.csv: model, metric, season, factor,
            ic_inf, ic_sup). Opcionales: "bands" (empirical_bands), "viirs_choice" (choose_viirs),
            "aqua_missing" (aqua_missing_weeks) y "end_week". Si faltan los tres últimos se
            calculan desde df_aggregated (para la tabla por celda conviene pasar los nacionales).
        target_years: años ISO del tramo estimado (2002-2011).
    Salidas:
        DataFrame (week, [cell, lat_c, lon_c], iso_year, iso_week, month, season, tramo, fuente,
        calidad, viirs_days, aqua_count, aqua_frp, factor_count, factor_frp, count, count_ic_inf,
        count_ic_sup, frp, frp_ic_inf, frp_ic_sup y, si hay "bands", count_inf, count_sup,
        frp_inf, frp_sup).
        tramo ∈ {estimado, VIIRS real}; fuente ∈ {estimado, S-NPP, NOAA-20, NOAA-21, sin dato};
        calidad ∈ {ok, parcial, relleno, sin dato}.
    """
    df = df_aggregated
    by_cell = "cell" in df.columns
    keys = ["week"] + (CELL_KEYS if by_cell else [])
    target_years = list(target_years)

    choice = model_fit.get("viirs_choice")
    choice = choose_viirs(df) if choice is None else choice
    missing = model_fit.get("aqua_missing")
    missing = aqua_missing_weeks(df) if missing is None else missing
    end_week = model_fit.get("end_week")
    end_week = last_complete_week(df) if end_week is None else end_week
    aqua_start = pd.Timestamp(HARMONIZE["aqua_start"])
    first_year = min(target_years)

    # Esqueleto: todas las filas (semana [× celda]) desde la primera semana de Aqua hasta end_week.
    df = df[(df["iso_year"] >= first_year) & (df["week"] <= end_week)]
    first_aqua = df.loc[df["sensor"] == REF_SENSOR, "week"].min()
    df = df[df["week"] >= first_aqua]
    base = df[keys + CALENDAR].drop_duplicates(keys)

    def _values(sensor_mask: pd.Series, prefix: str) -> pd.DataFrame:
        sub = df[sensor_mask][keys + list(METRICS.values())]
        sub = sub.groupby(keys, as_index=False)[list(METRICS.values())].sum()
        return sub.rename(columns={v: f"{prefix}_{k}" for k, v in METRICS.items()})

    out = base.merge(_values(df["sensor"] == REF_SENSOR, "aqua"), on=keys, how="left")
    out = out.merge(choice, on="week", how="left")
    # Valor VIIRS del satélite elegido en cada semana
    viirs = df.merge(choice, on="week", how="inner")
    viirs = viirs[viirs["sensor"] == viirs["viirs_sensor"]]
    vv = viirs.groupby(keys, as_index=False)[list(METRICS.values())].sum()
    out = out.merge(vv.rename(columns={v: f"viirs_{k}" for k, v in METRICS.items()}), on=keys, how="left")
    # En la tabla por celda una celda puede no tener fila del satélite elegido: es un cero explícito.
    has_viirs = out["viirs_sensor"].notna()
    for k in METRICS:
        out.loc[has_viirs, f"viirs_{k}"] = out.loc[has_viirs, f"viirs_{k}"].fillna(0.0)
        out[f"aqua_{k}"] = out[f"aqua_{k}"].fillna(0.0)

    out = out.merge(_factor_table(model_fit["factors"]), on="season", how="left")

    estimated_period = out["iso_year"].isin(target_years)
    use_viirs = ~estimated_period & has_viirs
    aqua_nan = out["week"].isin(set(missing))
    use_aqua = (estimated_period | ~has_viirs) & ~aqua_nan

    out["tramo"] = np.where(estimated_period, "estimado", "VIIRS real")
    out["fuente"] = np.select([use_viirs, use_aqua], [out["viirs_sensor"].map(SOURCE_LABELS), "estimado"],
                              default="sin dato")
    out["calidad"] = np.select(
        [use_viirs, use_aqua & ~estimated_period, use_aqua & (out["week"] + pd.Timedelta(days=6) >= aqua_start)
         & (out["week"] <= aqua_start), use_aqua],
        ["ok", "relleno", "parcial", "ok"], default="sin dato")

    for k in METRICS:
        est = out[f"aqua_{k}"] * out[f"factor_{k}"]
        out[k] = np.where(use_viirs, out[f"viirs_{k}"], np.where(use_aqua, est, np.nan))
        for b in ("ic_inf", "ic_sup"):
            est_b = out[f"aqua_{k}"] * out[f"{b}_{k}"]
            out[f"{k}_{b}"] = np.where(use_viirs, out[k], np.where(use_aqua, est_b, np.nan))
        # Los valores de Aqua en semanas sin dato no son ceros: se dejan NaN para no confundir.
        out.loc[aqua_nan, f"aqua_{k}"] = np.nan

    bands = model_fit.get("bands")
    if bands is not None:
        for k in METRICS:
            q = bands[bands["metric"] == k].set_index("season")
            for b, col in (("inf", "q_inf"), ("sup", "q_sup")):
                mult = out["season"].map(q[col]).astype(float)
                out[f"{k}_{b}"] = np.where(use_aqua, out[k] * mult, out[k])

    cols = keys + CALENDAR + ["tramo", "fuente", "calidad", "viirs_days", "aqua_count", "aqua_frp",
                              "factor_count", "factor_frp"]
    for k in METRICS:
        cols += [k, f"{k}_ic_inf", f"{k}_ic_sup"] + ([f"{k}_inf", f"{k}_sup"] if bands is not None else [])
    return out[cols].sort_values(keys).reset_index(drop=True)


def annual_totals(series: pd.DataFrame, annual: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Totales anuales de la serie nacional. Los NaN (sin dato) no se suman: se cuentan aparte.
    Banda anual: la parte estimada × [r_min, r_max] de validación; la parte real no tiene banda.
    """
    s = series.copy()
    est = s["fuente"].eq("estimado")
    rows = []
    for year, g in s.groupby("iso_year"):
        e = est.loc[g.index]
        row = {"iso_year": int(year), "tramo": g["tramo"].iloc[0], "n_weeks": int(len(g)),
               "weeks_estimado": int(e.sum()), "weeks_viirs": int(g["fuente"].isin(SOURCE_LABELS.values()).sum()),
               "weeks_sin_dato": int(g["fuente"].eq("sin dato").sum()),
               "fuentes": ", ".join(sorted(g.loc[g["fuente"] != "sin dato", "fuente"].unique()))}
        for k in METRICS:
            total = float(g[k].sum(skipna=True))
            row[k] = total
            row[f"{k}_ic_inf"] = float(g[f"{k}_ic_inf"].sum(skipna=True))
            row[f"{k}_ic_sup"] = float(g[f"{k}_ic_sup"].sum(skipna=True))
            if annual is not None:
                r = annual.set_index("metric").loc[k]
                part_est = float(g.loc[e, k].sum())
                row[f"{k}_inf"] = total - part_est + part_est * r["r_min"]
                row[f"{k}_sup"] = total - part_est + part_est * r["r_max"]
            row[f"aqua_{k}"] = float(g["aqua_" + k].sum(skipna=True))
        rows.append(row)
    return pd.DataFrame(rows)


def backcast_check(df_weekly: pd.DataFrame, factors: pd.DataFrame, model: str,
                   years: list[int]) -> pd.DataFrame:
    """
    Comprobación: aplica el factor final a Aqua en años con VIIRS y compara con el total VIIRS real
    (mismas semanas, S-NPP y NOAA-20). No es una validación independiente para 2012-2022 (esos años
    entraron al reajuste final); 2023-2024 sí quedan fuera.
    """
    rows = []
    for target in ("SNPP", "NOAA20"):
        if target not in set(df_weekly["sensor"]):
            continue
        for out_name, col in METRICS.items():
            pairs = paired_weeks(df_weekly, years, col, REF_SENSOR, target)
            pred = predict_target(pairs, factors, model, col)
            for year, g in pred.groupby("iso_year"):
                obs, est = g["target"].sum(), g["pred"].sum()
                rows.append({"target": target, "metric": out_name, "iso_year": int(year), "n_weeks": len(g),
                             "viirs_real": float(obs), "aqua_x_factor": float(est),
                             "error_pct": float(100 * (est - obs) / obs) if obs else np.nan})
    return pd.DataFrame(rows)


def band_coverage(df_weekly: pd.DataFrame, factors: pd.DataFrame, bands: pd.DataFrame, model: str,
                  years: list[int], target: str) -> dict:
    """Porcentaje de semanas en que el VIIRS observado cae dentro de la banda de predicción."""
    out = {}
    for out_name, col in METRICS.items():
        pairs = paired_weeks(df_weekly, years, col, REF_SENSOR, target)
        if pairs.empty:
            continue
        pred = predict_target(pairs, factors, model, col)
        q = bands[bands["metric"] == out_name].set_index("season")
        lo = pred["pred"] * pred["season"].map(q["q_inf"])
        hi = pred["pred"] * pred["season"].map(q["q_sup"])
        out[out_name] = {"n_weeks": int(len(pred)),
                         "coverage_pct": float(100 * pred["target"].between(lo, hi).mean())}
    return out


def plot_harmonized(series: pd.DataFrame, annual: pd.DataFrame, check: pd.DataFrame, path: Path) -> None:
    """Serie semanal única con bandas (arriba) y totales anuales con la comprobación Aqua × factor (abajo)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"estimado": "tab:blue", "S-NPP": "tab:orange", "NOAA-20": "tab:green", "NOAA-21": "tab:purple"}
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 9))
    s = series.set_index("week")
    est = s["fuente"].eq("estimado")
    ax1.fill_between(s.index, s["count_inf"].where(est), s["count_sup"].where(est), color="tab:blue",
                     alpha=0.2, lw=0, label="banda de predicción semanal (estimado)")
    ax1.plot(s.index, s["count"], color="0.6", lw=0.5, zorder=1)
    for fuente, color in colors.items():
        m = s["fuente"].eq(fuente)
        if m.any():
            ax1.scatter(s.index[m], s.loc[m, "count"], s=4, color=color, label=fuente, zorder=2)
    nan_weeks = s.index[s["fuente"].eq("sin dato")]
    for w in nan_weeks:
        ax1.axvspan(w, w + pd.Timedelta(days=7), color="red", alpha=0.25, lw=0)
    ax1.axvline(pd.Timestamp("2012-01-01"), color="k", ls="--", lw=1)
    ax1.text(pd.Timestamp("2012-02-01"), ax1.get_ylim()[1] * 0.92, "VIIRS real →", fontsize=9)
    ax1.text(pd.Timestamp("2011-12-01"), ax1.get_ylim()[1] * 0.92, "← estimado (Aqua × factor)",
             fontsize=9, ha="right")
    ax1.set_title("Serie única semanal de focos de calor en Perú (unidades VIIRS 375 m, conteo limpio)"
                  + (f" · rojo = sin dato ({len(nan_weeks)} semanas)" if len(nan_weeks) else ""))
    ax1.set_ylabel("focos por semana")
    ax1.legend(loc="upper left", markerscale=3, fontsize=8)

    a = annual
    bar_colors = ["tab:blue" if t == "estimado" else "tab:orange" for t in a["tramo"]]
    yerr = None
    if "count_inf" in a:
        yerr = np.vstack([a["count"] - a["count_inf"], a["count_sup"] - a["count"]])
    ax2.bar(a["iso_year"], a["count"], color=bar_colors, alpha=0.8, yerr=yerr, capsize=3)
    c = check[(check["metric"] == "count") & (check["target"] == "SNPP")]
    if not c.empty:
        ax2.plot(c["iso_year"], c["aqua_x_factor"], "o--", color="tab:blue", ms=4,
                 label="Aqua × factor en años con VIIRS (semanas pareadas con S-NPP)")
        ax2.plot(c["iso_year"], c["viirs_real"], "s", color="k", ms=4, mfc="none",
                 label="S-NPP real (mismas semanas)")
        ax2.legend(fontsize=8, loc="upper left")
    ax2.set_title("Total anual (azul = estimado con banda anual de validación; naranja = VIIRS real)")
    ax2.set_ylabel("focos por año")
    ax2.set_xticks(a["iso_year"])
    ax2.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def run_harmonization(df_weekly: pd.DataFrame, df_weekly_cell: pd.DataFrame | None,
                      final_factors: pd.DataFrame, calibration_factors: pd.DataFrame, model: str,
                      validation_years: list[int], out_dir: Path, plot_dir: Path | None = None,
                      target_years: list[int] | None = None) -> dict:
    """
    Pasos 7-8 del explainer: aplica el factor final a Aqua 2002-2011, une con VIIRS real y guarda
    la serie única nacional y por celda, los totales anuales, las bandas y los diagnósticos.
    """
    from aggregate import save_table

    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    lo, hi = HARMONIZE["estimated"]
    target_years = list(range(lo, hi + 1)) if target_years is None else target_years
    factors = final_factors[final_factors["model"] == model]

    bands = empirical_bands(df_weekly, calibration_factors, model, validation_years)
    annual_r = annual_band(df_weekly, calibration_factors, model, validation_years)
    bands.to_csv(out_dir / "harmonization_bands.csv", index=False)
    print(f"Bandas de predicción semanal ({HARMONIZE['band_coverage']:.0%}, observado/predicho en "
          f"validación {validation_years[0]}-{validation_years[-1]}):")
    print(bands.round(3).to_string(index=False))
    print("Banda anual (razón observado/predicho, S-NPP y NOAA-20):")
    print(annual_r.round(3).to_string(index=False))

    fit = {"factors": factors, "bands": bands, "viirs_choice": choose_viirs(df_weekly),
           "aqua_missing": aqua_missing_weeks(df_weekly), "end_week": last_complete_week(df_weekly)}
    series = apply_harmonization(df_weekly, fit, target_years)
    series.to_csv(out_dir / "harmonized_weekly.csv", index=False)
    annual = annual_totals(series, annual_r)
    annual.to_csv(out_dir / "harmonized_annual.csv", index=False)

    print(f"\nSerie única {series['week'].min():%Y-%m-%d} a {series['week'].max():%Y-%m-%d} "
          f"({len(series)} semanas)")
    print(series.groupby(["tramo", "fuente", "calidad"]).size().rename("semanas").to_string())
    print("\nSemanas sin dato:", ", ".join(f"{w:%Y-%m-%d}" for w in series.loc[series["fuente"] == "sin dato", "week"]))
    cols = ["iso_year", "tramo", "fuentes", "weeks_sin_dato", "aqua_count", "count", "count_inf", "count_sup",
            "frp", "frp_inf", "frp_sup"]
    print("\nTotales anuales (conteo y FRP en unidades VIIRS):")
    print(annual[cols].round(0).to_string(index=False))

    check_years = sorted(set(series.loc[series["tramo"] == "VIIRS real", "iso_year"]))
    check = backcast_check(df_weekly, factors, model, check_years)
    check.to_csv(out_dir / "harmonization_backcast_check.csv", index=False)
    coverage = {
        "validacion_SNPP (en muestra para los cuantiles)": band_coverage(
            df_weekly, calibration_factors, bands, model, validation_years, "SNPP"),
        "validacion_NOAA20": band_coverage(df_weekly, calibration_factors, bands, model, validation_years, "NOAA20"),
        "2023-2024_SNPP (factor final, fuera de muestra)": band_coverage(
            df_weekly, factors, bands, model, [2023, 2024], "SNPP"),
        "2023-2024_NOAA20 (factor final, fuera de muestra)": band_coverage(
            df_weekly, factors, bands, model, [2023, 2024], "NOAA20"),
    }
    print("\nCobertura de la banda semanal:")
    for k, v in coverage.items():
        print(f"  {k}: " + ", ".join(f"{m} {d['coverage_pct']:.0f} % de {d['n_weeks']} semanas" for m, d in v.items()))

    from validation import prediction_report
    prediction = prediction_report(df_weekly, final_factors, calibration_factors, model, bands,
                                   out_dir, plot_dir, last_year=int(series["iso_year"].max()))

    cell = None
    if df_weekly_cell is not None:
        cell_fit = {k: v for k, v in fit.items() if k != "bands"}  # bandas empíricas solo a nivel nacional
        cell = apply_harmonization(df_weekly_cell, cell_fit, target_years)
        path = save_table(cell, out_dir, "harmonized_weekly_cell")
        nat = series.set_index("week")["count"]
        cell_sum = cell.groupby("week")["count"].sum(min_count=1)
        diff = (cell_sum - nat.reindex(cell_sum.index)).abs().max()
        print(f"\nSerie por celda: {len(cell)} filas -> {path.name} "
              f"(máx. diferencia suma de celdas vs nacional: {diff:.2e})")

    summary = {
        "modelo": model, "tramo_estimado": target_years, "factores": factors.round(4).to_dict("records"),
        "prioridad_viirs": list(VIIRS_PRIORITY), "min_dias_viirs": MIN_TARGET_DAYS,
        "aqua_gaps": HARMONIZE["aqua_gaps"], "band_coverage": HARMONIZE["band_coverage"],
        "semana_inicio": f"{series['week'].min():%Y-%m-%d}", "semana_fin": f"{series['week'].max():%Y-%m-%d}",
        "semanas_por_fuente": series["fuente"].value_counts().to_dict(),
        "semanas_por_calidad": series["calidad"].value_counts().to_dict(),
        "semanas_sin_dato": [f"{w:%Y-%m-%d}" for w in series.loc[series["fuente"] == "sin dato", "week"]],
        "banda_anual": annual_r.round(4).to_dict("records"), "cobertura_banda_semanal": coverage,
    }
    (out_dir / "harmonize_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                   encoding="utf-8")
    if plot_dir is not None:
        plot_dir.mkdir(parents=True, exist_ok=True)
        plot_harmonized(series, annual, check, plot_dir / "harmonized_series.png")

    print(f"\nTablas guardadas en: {out_dir}")
    return {"series": series, "annual": annual, "cell": cell, "bands": bands, "check": check,
            "prediction": prediction}
