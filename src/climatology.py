"""
Módulo de climatología y anomalías sobre la serie única armonizada (unidades VIIRS).

    * Línea base (compute_baseline): por mes del año (1-12) o semana ISO del año (1-52), con los años
      de settings.yaml -> climatology.baseline (2003-2024). Estadísticos: media, mediana, p10, p25,
      p75, p90, mínimo y máximo, con el año en que ocurrieron.
    * Anomalías (compute_anomalies): diferencia y % frente a la mediana, percentil empírico dentro de
      la línea base y categoría de semáforo:
          muy por debajo (< p10) · por debajo (p10-p25) · normal (p25-p75) · por encima (p75-p90)
          · muy por encima (> p90) · máximo histórico (>= máximo de la línea base)
      En los meses/semanas estimados (2002-2011) se calcula la categoría con la banda inferior y la
      superior: si no coinciden, categoria_incierta = True (la incertidumbre del factor cambia el color).
    * Meses o semanas con datos faltantes (calidad "incompleto", "parcial" o "sin dato") no entran en
      la línea base y su categoría es "sin dato completo".
    * Áreas de interés (settings.yaml -> climatology.aoi_*): suma de celdas de 0.25° cuyo centro cae
      en el rectángulo. Usan el factor nacional (el modelo C por zona está pendiente) y no tienen banda.

Los percentiles de una suma de celdas no son la suma de percentiles: la climatología de un área se
calcula siempre después de sumar sus celdas (region_monthly), nunca sumando climatologías de celdas.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import CLIMATOLOGY

CATEGORIES = ["muy por debajo", "por debajo", "normal", "por encima", "muy por encima", "máximo histórico"]
NO_DATA = "sin dato completo"
# Paleta divergente apta para daltonismo (PuOr de ColorBrewer) + tono oscuro para el máximo histórico.
CATEGORY_COLORS = {
    "muy por debajo": "#5e3c99", "por debajo": "#b2abd2", "normal": "#f7f7f7",
    "por encima": "#fdb863", "muy por encima": "#e66101", "máximo histórico": "#7f2704",
    NO_DATA: "#bdbdbd",
}
BAD_QUALITY = {"incompleto", "parcial", "sin dato"}
MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# ---------------------------------------------------------------------------
# Preparación de series
# ---------------------------------------------------------------------------
def weekly_frame(series: pd.DataFrame) -> pd.DataFrame:
    """Serie semanal armonizada -> (year, period=semana ISO, ...). La semana 53 se une a la 52."""
    out = series.rename(columns={"iso_year": "year"}).copy()
    out["period"] = out["iso_week"].clip(upper=52)
    return out


def monthly_frame(monthly: pd.DataFrame) -> pd.DataFrame:
    """Serie mensual armonizada -> (year, period=mes, ...)."""
    return monthly.assign(period=monthly["month"])


def region_monthly(monthly_cell: pd.DataFrame, monthly_national: pd.DataFrame,
                   bbox: list[float]) -> pd.DataFrame:
    """
    Serie mensual de un área: suma de las celdas de análisis (0.25°, lat_025/lon_025) cuyo centro cae en
    bbox = [lat_min, lat_max, lon_min, lon_max]. Se usa la celda de 0.25° y no la del mapa (0.1° desde
    2012) para que el área tenga los mismos bordes en todos los años. Los meses sin focos en el área son
    ceros explícitos; la calidad/fuente es la nacional.
    """
    lat_min, lat_max, lon_min, lon_max = bbox
    lat, lon = ("lat_025", "lon_025") if "lat_025" in monthly_cell else ("lat_c", "lon_c")
    c = monthly_cell[monthly_cell[lat].between(lat_min, lat_max)
                     & monthly_cell[lon].between(lon_min, lon_max)]
    tot = c.groupby(["year", "month"], as_index=False)[["count", "frp"]].sum()
    base_cols = ["year", "month", "season", "tramo", "fuente", "calidad", "preliminar", "dias_mes", "dias",
                 "dias_estimado", "dias_sin_dato", "dias_preliminar"]
    base = monthly_national[[c for c in base_cols if c in monthly_national]]
    out = base.merge(tot, on=["year", "month"], how="left")
    out[["count", "frp"]] = out[["count", "frp"]].fillna(0.0)
    out.attrs["n_cells"] = int(c["cell_025" if "cell_025" in c else "cell"].nunique())
    return out


# ---------------------------------------------------------------------------
# Línea base y anomalías
# ---------------------------------------------------------------------------
MIN_PARTIAL_COVERAGE = 0.9  # un mes "parcial" con >= 90 % de sus días se considera completo


def _usable(df: pd.DataFrame, value: str) -> pd.Series:
    """Filas válidas para la línea base, las anomalías y el ranking (sin días faltantes relevantes)."""
    ok = df[value].notna()
    if "calidad" in df.columns:
        bad = df["calidad"].isin(BAD_QUALITY)
        if {"dias", "dias_mes"} <= set(df.columns):  # serie mensual: tolera el último mes casi completo
            bad &= ~(df["calidad"].eq("parcial") & (df["dias"] >= MIN_PARTIAL_COVERAGE * df["dias_mes"]))
        ok &= ~bad
    return ok


def compute_baseline(df_harmonized: pd.DataFrame, baseline_years: list[int], value: str = "count",
                     period: str = "period") -> pd.DataFrame:
    """
    Estadísticas climatológicas por período del año (mes o semana ISO).

    Entradas:
        df_harmonized: serie con columnas year, `period` y `value` (weekly_frame / monthly_frame /
            region_monthly + monthly_frame). Las filas con calidad incompleta no entran.
        baseline_years: años de la línea base (lista explícita).
    Salidas:
        DataFrame (period, n_years, media, mediana, p10, p25, p75, p90, minimo, anio_minimo, maximo,
        anio_maximo). Guarda en .attrs la muestra de la línea base (para percentiles empíricos).
    """
    d = df_harmonized[df_harmonized["year"].isin(baseline_years) & _usable(df_harmonized, value)]
    g = d.groupby(period)[value]
    base = pd.DataFrame({
        "n_years": g.size(), "media": g.mean(), "mediana": g.median(),
        "p10": g.quantile(0.10), "p25": g.quantile(0.25), "p75": g.quantile(0.75), "p90": g.quantile(0.90),
        "minimo": g.min(), "maximo": g.max(),
    })
    base["anio_minimo"] = d.loc[g.idxmin(), "year"].to_numpy()
    base["anio_maximo"] = d.loc[g.idxmax(), "year"].to_numpy()
    base = base.reset_index()
    base.attrs.update(sample=d[[period, value]].copy(), value=value, period=period,
                      years=list(baseline_years))
    return base


def _category(v: pd.Series, b: pd.DataFrame) -> pd.Series:
    cat = np.select(
        [v >= b["maximo"], v > b["p90"], v > b["p75"], v >= b["p25"], v >= b["p10"], v < b["p10"]],
        ["máximo histórico", "muy por encima", "por encima", "normal", "por debajo", "muy por debajo"],
        default=NO_DATA)
    return pd.Series(cat, index=v.index)


def compute_anomalies(df_harmonized: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    """
    Desviaciones frente a la línea base y categoría de semáforo para cada año × período.

    Salidas: columnas de entrada + mediana, p10, p25, p75, p90, maximo, anomalia (valor - mediana),
    anomalia_pct, percentil (0-100, empírico dentro de la línea base), categoria y, si hay bandas
    (`{value}_inf`/`{value}_sup`), categoria_inf, categoria_sup y categoria_incierta.
    """
    value, period = baseline.attrs.get("value", "count"), baseline.attrs.get("period", "period")
    stats = ["mediana", "p10", "p25", "p75", "p90", "maximo"]
    out = df_harmonized.merge(baseline[[period] + stats], on=period, how="left")
    v = out[value]
    out["anomalia"] = v - out["mediana"]
    out["anomalia_pct"] = np.where(out["mediana"] > 0, 100 * (v / out["mediana"] - 1), np.nan)

    sample = baseline.attrs["sample"]
    groups = {p: np.sort(s.to_numpy()) for p, s in sample.groupby(period)[value]}

    def _pct(row_v, row_p):
        arr = groups.get(row_p)
        if arr is None or np.isnan(row_v):
            return np.nan
        below = np.searchsorted(arr, row_v, side="left")
        equal = np.searchsorted(arr, row_v, side="right") - below
        return 100 * (below + 0.5 * equal) / len(arr)

    out["percentil"] = [_pct(a, b) for a, b in zip(v, out[period])]
    usable = _usable(out, value)
    out["categoria"] = _category(v, out).where(usable, NO_DATA)
    if f"{value}_inf" in out and f"{value}_sup" in out:
        out["categoria_inf"] = _category(out[f"{value}_inf"], out).where(usable, NO_DATA)
        out["categoria_sup"] = _category(out[f"{value}_sup"], out).where(usable, NO_DATA)
        out["categoria_incierta"] = out["categoria_inf"] != out["categoria_sup"]
    return out


def annual_ranking(monthly: pd.DataFrame, baseline_years: list[int]) -> pd.DataFrame:
    """Total anual, mes pico, anomalía frente a la mediana anual de la línea base y puesto (años completos)."""
    rows = []
    for year, g in monthly.groupby("year"):
        complete = len(g) == 12 and bool(_usable(g, "count").all())
        peak = g.loc[g["count"].idxmax()]
        row = {"year": int(year), "tramo": g["tramo"].iloc[0], "completo": bool(complete),
               "preliminar": bool(g["preliminar"].any()) if "preliminar" in g else False,
               "count": float(g["count"].sum()), "frp": float(g["frp"].sum()),
               "mes_pico": int(peak["month"]), "count_mes_pico": float(peak["count"]),
               "pct_en_ago_sep": float(100 * g.loc[g["month"].isin([8, 9]), "count"].sum() / g["count"].sum())}
        # Sin banda: sumar bandas mensuales la exageraría (los errores se compensan dentro del año).
        # La banda anual validada está en harmonized_annual.csv.
        rows.append(row)
    r = pd.DataFrame(rows)
    ref = r[r["completo"] & r["year"].isin(baseline_years)]
    med = ref["count"].median()
    r["anomalia_pct"] = 100 * (r["count"] / med - 1)
    r["puesto"] = r["count"].where(r["completo"]).rank(ascending=False, method="min").astype("Int64")
    r["percentil"] = [100 * (ref["count"] < c).mean() if ok else np.nan for c, ok in zip(r["count"], r["completo"])]
    return r


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def plot_calendar(anom: pd.DataFrame, ranking: pd.DataFrame, title: str, path: Path) -> None:
    """Calendario año × mes: conteo (escala log, inferno) y semáforo de anomalías, con totales anuales."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, LogNorm
    from matplotlib.patches import Patch

    years = sorted(anom["year"].unique())
    grid = anom.pivot(index="year", columns="month", values="count").reindex(index=years, columns=range(1, 13))
    cats = anom.pivot(index="year", columns="month", values="categoria").reindex(index=years, columns=range(1, 13))
    unc = (anom.pivot(index="year", columns="month", values="categoria_incierta")
               .reindex(index=years, columns=range(1, 13)) if "categoria_incierta" in anom else None)
    prel = (anom.pivot(index="year", columns="month", values="preliminar")
                .reindex(index=years, columns=range(1, 13)) if "preliminar" in anom else None)
    tramo = anom.drop_duplicates("year").set_index("year")["tramo"]
    prel_years = set(anom.loc[anom["preliminar"].fillna(False).astype(bool), "year"]) if prel is not None else set()
    labels = [f"{y}{' *' if tramo.get(y) == 'estimado' else ''}{' p' if y in prel_years else ''}" for y in years]

    def _is_prel(i, j):
        return prel is not None and bool(prel.iloc[i, j] == True)  # noqa: E712 (celdas NaN -> False)

    fig, axes = plt.subplots(1, 3, figsize=(17, 0.36 * len(years) + 2.8),
                             gridspec_kw={"width_ratios": [12, 12, 4]})
    ax = axes[0]
    vmax = np.nanmax(grid.to_numpy())
    im = ax.imshow(grid.clip(lower=1).to_numpy(), cmap="inferno_r", norm=LogNorm(vmin=1, vmax=vmax), aspect="auto")
    for i, y in enumerate(years):
        for j in range(12):
            val = grid.iloc[i, j]
            if np.isnan(val):
                continue
            txt = f"{val / 1000:.1f}k" if val >= 1000 else f"{val:.0f}"
            txt += "p" if _is_prel(i, j) else ""
            ax.text(j, i, txt, ha="center", va="center", fontsize=6.5,
                    color="white" if val > vmax ** 0.6 else "black")
    ax.set_title("Focos por mes (unidades VIIRS)")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)

    ax = axes[1]
    order = list(CATEGORY_COLORS)
    codes = cats.apply(lambda col: col.map({c: i for i, c in enumerate(order)})).to_numpy(dtype=float)
    ax.imshow(codes, cmap=ListedColormap([CATEGORY_COLORS[c] for c in order]), vmin=-0.5,
              vmax=len(order) - 0.5, aspect="auto")
    pct = anom.pivot(index="year", columns="month", values="percentil").reindex(index=years, columns=range(1, 13))
    for i in range(len(years)):
        for j in range(12):
            p, c = pct.iloc[i, j], cats.iloc[i, j]
            if _is_prel(i, j):  # contorno punteado: dato NRT preliminar
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec="k", lw=1.0, ls=(0, (2, 1.5))))
            if c == NO_DATA or np.isnan(p):
                continue
            mark = "?" if unc is not None and bool(unc.iloc[i, j]) else ""
            mark += "p" if _is_prel(i, j) else ""
            ax.text(j, i, f"{p:.0f}{mark}", ha="center", va="center", fontsize=6.5,
                    color="white" if c in ("muy por debajo", "muy por encima", "máximo histórico") else "black")
    ax.set_title("Anomalía: percentil del mes en la línea base (? = la banda cambia la categoría; "
                 "p y borde punteado = preliminar NRT)", fontsize=10)
    ax.legend(handles=[Patch(color=CATEGORY_COLORS[c], label=c) for c in order], loc="upper center",
              bbox_to_anchor=(0.5, -0.03), ncol=4, fontsize=7.5, frameon=False)

    for ax in axes[:2]:
        ax.set_xticks(range(12))
        ax.set_xticklabels(MONTHS_ES)
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.xaxis.tick_top()

    ax = axes[2]
    r = ranking.set_index("year").reindex(years)
    colors = ["#3b528b" if tramo.get(y) == "estimado" else "#21918c" for y in years]
    bars = ax.barh(range(len(years)), r["count"], color=colors)
    for bar, complete in zip(bars, r["completo"]):
        bar.set_alpha(1.0 if complete else 0.4)
    from matplotlib.ticker import FuncFormatter
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1000:.0f}k"))
    ax.set_xlim(0, r["count"].max() * 1.25)
    for i, (y, row) in enumerate(r.iterrows()):
        if pd.notna(row["puesto"]):
            ax.text(row["count"], i, f" #{int(row['puesto'])}", va="center", fontsize=7)
    ax.set_ylim(len(years) - 0.5, -0.5)
    ax.set_yticks([])
    ax.set_title("Total anual y puesto")
    ax.tick_params(axis="x", labelsize=7)

    fig.suptitle(f"{title}  ·  * = estimado (Aqua × factor), resto VIIRS real  ·  p = preliminar (NRT)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_weekly_climatology(anom_w: pd.DataFrame, baseline_w: pd.DataFrame, years_to_show: list[int],
                            title: str, path: Path) -> None:
    """Climatología semanal: mediana, p25-p75 y p10-p90, con los años elegidos superpuestos."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    b = baseline_w.sort_values("period")
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.fill_between(b["period"], b["p10"], b["p90"], color="0.85", label="p10-p90")
    ax.fill_between(b["period"], b["p25"], b["p75"], color="0.65", label="p25-p75")
    ax.plot(b["period"], b["mediana"], color="k", lw=1.8, label="mediana")
    palette = ["#e66101", "#5e3c99", "#1b9e77", "#d95f02"]
    for color, y in zip(palette, years_to_show):
        g = anom_w[anom_w["year"] == y].sort_values("period")
        if "preliminar" in g and g["preliminar"].any():
            # Tramo NRT punteado; se repite la última semana definitiva para que la línea no se corte
            pm = g["preliminar"].fillna(False).astype(bool).to_numpy()
            first = int(np.argmax(pm))
            ax.plot(g["period"].iloc[:first + 1], g["count"].iloc[:first + 1], color=color, lw=1.4, label=str(y))
            ax.plot(g["period"].iloc[max(first - 1, 0):], g["count"].iloc[max(first - 1, 0):], color=color, lw=1.4,
                    ls=(0, (3, 2)), label=f"{y} preliminar (NRT)")
            continue
        ax.plot(g["period"], g["count"], color=color, lw=1.4, label=str(y))
    starts = pd.date_range("2024-01-01", periods=12, freq="MS")  # 2024: el 1-ene cae en la semana ISO 1
    ax.set_xticks(starts.isocalendar().week.clip(upper=52).to_numpy())
    ax.set_xticklabels(MONTHS_ES)
    ax.set_xlim(1, 52)
    ax.set_ylabel("focos por semana (unidades VIIRS)")
    ax.set_title(title)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------
def run_climatology(weekly: pd.DataFrame, monthly: pd.DataFrame, monthly_cell: pd.DataFrame | None,
                    out_dir: Path, plot_dir: Path | None = None,
                    baseline_years: list[int] | None = None) -> dict:
    """Paso 9 del explainer: climatología, anomalías, ranking y calendario (Perú y áreas de interés)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    lo, hi = CLIMATOLOGY["baseline"] if baseline_years is None else (baseline_years[0], baseline_years[-1])
    years = list(range(lo, hi + 1))
    print(f"Línea base: {lo}-{hi} ({len(years)} años)")

    scopes = {"peru": monthly_frame(monthly)}
    if monthly_cell is not None:
        for name, bbox in CLIMATOLOGY["aois"].items():
            reg = region_monthly(monthly_cell, monthly, bbox)
            print(f"Área '{name}' (rectángulo {bbox}): {reg.attrs['n_cells']} celdas de 0.25°")
            scopes[name] = monthly_frame(reg)

    clim_m, anom_m, ranks, summary = [], [], [], {"linea_base": [lo, hi], "ambitos": {}}
    for name, df in scopes.items():
        base = compute_baseline(df, years)
        anom = compute_anomalies(df, base)
        rank = annual_ranking(df, years)
        plain = base.assign(ambito=name)
        plain.attrs = {}  # la muestra guardada en attrs no se puede concatenar
        clim_m.append(plain)
        anom_m.append(anom.assign(ambito=name))
        ranks.append(rank.assign(ambito=name))
        top = rank[rank["completo"]].nsmallest(5, "puesto")
        peak_month = int(base.loc[base["mediana"].idxmax(), "period"])
        last = int(df["year"].max())
        summary["ambitos"][name] = {
            "mes_pico_mediana": MONTHS_ES[peak_month - 1],
            "pct_mediana_en_ago_sep": float(100 * base.loc[base["period"].isin([8, 9]), "mediana"].sum()
                                            / base["mediana"].sum()),
            "top5_anios": top[["year", "count", "tramo"]].round(0).to_dict("records"),
            "meses_muy_por_encima_o_record": anom.loc[anom["categoria"].isin(CATEGORIES[-2:]),
                                                      ["year", "month", "count", "categoria"]]
                                                  .round(0).to_dict("records")[-12:],
            f"categorias_{last}": anom.loc[anom["year"] == last].set_index("month")["categoria"].to_dict(),
        }
        print(f"\n[{name}] climatología mensual (mediana y p10-p90, focos/mes):")
        print(base[["period", "n_years", "mediana", "p10", "p90", "maximo", "anio_maximo"]]
              .round(0).to_string(index=False))
        print(f"[{name}] top 5 años completos: "
              + ", ".join(f"{int(r.year)} ({r['count']:,.0f}{', est.' if r.tramo == 'estimado' else ''})"
                          for _, r in top.iterrows()))
        if plot_dir is not None:
            plot_dir.mkdir(parents=True, exist_ok=True)
            label = "Perú" if name == "peru" else f"Área '{name}' (provisional)"
            plot_calendar(anom, rank, f"Calendario de actividad de quema · {label}",
                          plot_dir / f"calendar_{name}.png")

    clim_m = pd.concat(clim_m, ignore_index=True).rename(columns={"period": "month"})
    anom_m = pd.concat(anom_m, ignore_index=True).drop(columns="period")
    ranks = pd.concat(ranks, ignore_index=True)
    clim_m.to_csv(out_dir / "climatology_monthly.csv", index=False)
    anom_m.to_csv(out_dir / "anomalies_monthly.csv", index=False)
    ranks.to_csv(out_dir / "annual_ranking.csv", index=False)

    # Semanal (solo Perú: la tabla semanal por celda ya existe si se necesita por área)
    wk = weekly_frame(weekly)
    base_w = compute_baseline(wk, years)
    anom_w = compute_anomalies(wk, base_w)
    base_w.rename(columns={"period": "iso_week"}).to_csv(out_dir / "climatology_weekly.csv", index=False)
    anom_w.drop(columns="period").to_csv(out_dir / "anomalies_weekly.csv", index=False)
    if plot_dir is not None:
        r = ranks[(ranks["ambito"] == "peru") & ranks["completo"]]
        show = [int(wk["year"].max()), int(r.loc[r["puesto"].idxmin(), "year"])]
        plot_weekly_climatology(anom_w, base_w, list(dict.fromkeys(show)),
                                f"Climatología semanal de focos en Perú ({lo}-{hi})",
                                plot_dir / "climatology_weekly_peru.png")

    cat_counts = anom_m[anom_m["ambito"] == "peru"]["categoria"].value_counts().to_dict()
    unc = anom_m[(anom_m["ambito"] == "peru") & (anom_m["tramo"] == "estimado")]
    summary["peru_categorias_meses"] = cat_counts
    if "categoria_incierta" in unc:
        summary["peru_pct_meses_estimados_con_categoria_incierta"] = float(100 * unc["categoria_incierta"].mean())
    (out_dir / "climatology_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False,
                                                                 default=str), encoding="utf-8")
    print(f"\nCategorías de los meses (Perú): {cat_counts}")
    if "peru_pct_meses_estimados_con_categoria_incierta" in summary:
        print(f"Meses estimados cuya categoría cambia dentro de la banda: "
              f"{summary['peru_pct_meses_estimados_con_categoria_incierta']:.0f} %")
    print(f"Tablas guardadas en: {out_dir}")
    return {"climatology_monthly": clim_m, "anomalies_monthly": anom_m, "ranking": ranks,
            "climatology_weekly": base_w, "anomalies_weekly": anom_w}
