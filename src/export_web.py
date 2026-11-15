"""
Módulo de exportación para la interfaz web (formato A: un JSON por vista).

Lee las tablas de output/processed/ (salidas de harmonize y climatology) y escribe en output/web/:

    meta.json                   leyenda, categorías del semáforo, ámbitos, tramos, factores, índice de archivos
    calendar_{ambito}.json      matriz año × mes con anomalías (calendario)
    series_weekly_peru.json     serie semanal nacional con bandas y anomalías
    climatology_{ambito}.json   curva típica por mes (y por semana ISO en Perú)
    ranking_{ambito}.json       años ordenados por total
    cells_index.json            celdas de 0.25° (id, centro, ámbitos a los que pertenecen)
    cells_{AAAA}.json           totales anuales y mensuales por celda (mapa, carga perezosa)
    regional_summary.csv        resumen ligero ámbito × año

El contrato de cada archivo está en docs/frontend_datos.md. Reglas comunes:
    * "sin dato" es null, nunca 0 (un 0 es un cero real de detecciones).
    * Conteos y FRP redondeados a enteros; porcentajes y percentiles a 1 decimal.
    * Las categorías usan ids sin acentos (muy_por_debajo ... maximo, sin_dato); la etiqueta
      con acentos y el color están en meta.json.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

from climatology import CATEGORIES, CATEGORY_COLORS, NO_DATA
from config import CELL_SIZE, CLIMATOLOGY, HARMONIZE, SEASONS

SCHEMA_VERSION = "1.0"

# Etiqueta de climatology.py -> id estable para el frontend
CATEGORY_IDS = {
    "muy por debajo": "muy_por_debajo",
    "por debajo": "por_debajo",
    "normal": "normal",
    "por encima": "por_encima",
    "muy por encima": "muy_por_encima",
    "máximo histórico": "maximo",
    NO_DATA: "sin_dato",
}
AMBITO_NAMES = {"peru": "Perú", "cusco": "Cusco"}


# ---------------------------------------------------------------------------
# Utilidades de conversión
# ---------------------------------------------------------------------------
def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA or v is pd.NaT


def _int(v):
    return None if _missing(v) else int(round(float(v)))


def _f1(v):
    return None if _missing(v) else round(float(v), 1)


def _f3(v):
    return None if _missing(v) else round(float(v), 3)


def _str(v):
    return None if _missing(v) else str(v)


def _bool(v):
    return None if _missing(v) else bool(v)


def _cat(v):
    return None if _missing(v) else CATEGORY_IDS[str(v)]


def _records(df: pd.DataFrame, spec: dict[str, tuple[str, callable]]) -> list[dict]:
    """Convierte filas a dicts con {nombre_json: conv(df[columna])}; columnas ausentes -> null."""
    cols = {out: (src, conv) for out, (src, conv) in spec.items()}
    rows = []
    for rec in df.to_dict("records"):
        rows.append({out: conv(rec.get(src)) for out, (src, conv) in cols.items()})
    return rows


def _blank_no_data(rows: list[dict]) -> list[dict]:
    """Con cat = sin_dato la anomalía y el percentil comparan un período incompleto: se anulan."""
    for r in rows:
        if r.get("cat") == "sin_dato":
            r.update(anomalia=None, anomalia_pct=None, percentil=None)
    return rows


def _write_json(obj, path: Path) -> int:
    """Escribe JSON compacto en UTF-8 (sin NaN: allow_nan=False falla si se cuela alguno)."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _tramo_id(v):
    """'estimado' / 'VIIRS real' -> 'estimado' / 'viirs_real'."""
    return None if _missing(v) else ("estimado" if v == "estimado" else "viirs_real")


# ---------------------------------------------------------------------------
# Especificaciones de columnas (nombre JSON -> (columna origen, conversión))
# ---------------------------------------------------------------------------
_ANOMALY_COLS = {
    "mediana": ("mediana", _int),
    "p10": ("p10", _int),
    "p25": ("p25", _int),
    "p75": ("p75", _int),
    "p90": ("p90", _int),
    "maximo": ("maximo", _int),
    "anomalia": ("anomalia", _int),
    "anomalia_pct": ("anomalia_pct", _f1),
    "percentil": ("percentil", _f1),
    "cat": ("categoria", _cat),
    "cat_inf": ("categoria_inf", _cat),
    "cat_sup": ("categoria_sup", _cat),
    "incierta": ("categoria_incierta", _bool),
}

CALENDAR_SPEC = {
    "anio": ("year", _int),
    "mes": ("month", _int),
    "temporada": ("season", _str),
    "tramo": ("tramo", _tramo_id),
    "fuente": ("fuente", _str),
    "calidad": ("calidad", _str),
    "dias_mes": ("dias_mes", _int),
    "dias_estimado": ("dias_estimado", _int),
    "dias_sin_dato": ("dias_sin_dato", _int),
    "count": ("count", _int),
    "count_inf": ("count_inf", _int),
    "count_sup": ("count_sup", _int),
    "frp": ("frp", _int),
    "frp_inf": ("frp_inf", _int),
    "frp_sup": ("frp_sup", _int),
    **_ANOMALY_COLS,
}

WEEKLY_SPEC = {
    "semana": ("week", _str),
    "anio": ("year", _int),
    "semana_iso": ("iso_week", _int),
    "mes": ("month", _int),
    "temporada": ("season", _str),
    "tramo": ("tramo", _tramo_id),
    "fuente": ("fuente", _str),
    "calidad": ("calidad", _str),
    "dias_viirs": ("viirs_days", _int),
    "count": ("count", _int),
    "count_inf": ("count_inf", _int),
    "count_sup": ("count_sup", _int),
    "count_ic_inf": ("count_ic_inf", _int),
    "count_ic_sup": ("count_ic_sup", _int),
    "frp": ("frp", _int),
    "frp_inf": ("frp_inf", _int),
    "frp_sup": ("frp_sup", _int),
    "frp_ic_inf": ("frp_ic_inf", _int),
    "frp_ic_sup": ("frp_ic_sup", _int),
    "aqua_count": ("aqua_count", _int),
    "factor_count": ("factor_count", _f3),
    **_ANOMALY_COLS,
}

CLIMATOLOGY_SPEC = {
    "n_anios": ("n_years", _int),
    "media": ("media", _int),
    "mediana": ("mediana", _int),
    "p10": ("p10", _int),
    "p25": ("p25", _int),
    "p75": ("p75", _int),
    "p90": ("p90", _int),
    "minimo": ("minimo", _int),
    "maximo": ("maximo", _int),
    "anio_minimo": ("anio_minimo", _int),
    "anio_maximo": ("anio_maximo", _int),
}

RANKING_SPEC = {
    "anio": ("year", _int),
    "tramo": ("tramo", _tramo_id),
    "completo": ("completo", _bool),
    "puesto": ("puesto", _int),
    "percentil": ("percentil", _f1),
    "count": ("count", _int),
    "frp": ("frp", _int),
    "anomalia_pct": ("anomalia_pct", _f1),
    "mes_pico": ("mes_pico", _int),
    "count_mes_pico": ("count_mes_pico", _int),
    "pct_ago_sep": ("pct_en_ago_sep", _f1),
}


# ---------------------------------------------------------------------------
# Contratos públicos (firmas acordadas con el equipo)
# ---------------------------------------------------------------------------
def export_calendar_json(df_anomalies: pd.DataFrame, out_path: Path) -> None:
    """
    Exporta el calendario año × mes de UN ámbito (filas de anomalies_monthly.csv ya filtradas por
    `ambito`) a out_path. Ver docs/frontend_datos.md -> calendar_{ambito}.json.
    """
    ambitos = df_anomalies["ambito"].unique() if "ambito" in df_anomalies else ["peru"]
    if len(ambitos) != 1:
        raise ValueError(f"export_calendar_json espera un solo ámbito, recibió {list(ambitos)}")
    df = df_anomalies.sort_values(["year", "month"])
    obj = {
        "version": SCHEMA_VERSION,
        "ambito": str(ambitos[0]),
        "linea_base": CLIMATOLOGY["baseline"],
        "anios": [int(df["year"].min()), int(df["year"].max())],
        "tiene_bandas": bool(df["count_inf"].notna().any()),
        "meses": _blank_no_data(_records(df, CALENDAR_SPEC)),
    }
    _write_json(obj, out_path)


def export_regional_summary_csv(df_anomalies: pd.DataFrame, out_path: Path) -> None:
    """
    Resumen ligero ámbito × año a partir de anomalies_monthly.csv: totales, mes de mayor conteo y
    cuántos meses quedaron sobre/bajo lo normal o sin dato completo.
    """
    df = df_anomalies.copy()
    df["cat"] = df["categoria"].map(CATEGORY_IDS)
    above, below = {"por_encima", "muy_por_encima", "maximo"}, {"por_debajo", "muy_por_debajo"}
    rows = []
    for (ambito, year), g in df.groupby(["ambito", "year"], sort=True):
        top = g.loc[g["count"].idxmax()]
        rows.append({
            "ambito": ambito,
            "anio": int(year),
            "tramo": _tramo_id(g["tramo"].iloc[0]),
            "n_meses": len(g),
            "count": _int(g["count"].sum()),
            "frp": _int(g["frp"].sum()),
            "mes_max": int(top["month"]),
            "count_mes_max": _int(top["count"]),
            "cat_mes_max": top["cat"],
            "meses_sobre_normal": int(g["cat"].isin(above).sum()),
            "meses_bajo_normal": int(g["cat"].isin(below).sum()),
            "meses_sin_dato": int((g["cat"] == "sin_dato").sum()),
            "meses_inciertos": int(g["categoria_incierta"].fillna(False).astype(bool).sum()),
        })
    pd.DataFrame(rows).to_csv(out_path, index=False, encoding="utf-8")


# ---------------------------------------------------------------------------
# Resto de vistas
# ---------------------------------------------------------------------------
def export_weekly_series_json(df_weekly: pd.DataFrame, out_path: Path) -> None:
    """Serie semanal nacional (anomalies_weekly.csv) con bandas de predicción e IC del factor."""
    df = df_weekly.sort_values("week").copy()
    df["week"] = pd.to_datetime(df["week"]).dt.strftime("%Y-%m-%d")
    obj = {
        "version": SCHEMA_VERSION,
        "ambito": "peru",
        "linea_base": CLIMATOLOGY["baseline"],
        "semana_inicio": df["week"].iloc[0],
        "semana_fin": df["week"].iloc[-1],
        "cobertura_banda": HARMONIZE["band_coverage"],
        "semanas": _blank_no_data(_records(df, WEEKLY_SPEC)),
    }
    _write_json(obj, out_path)


def export_climatology_json(ambito: str, clim_monthly: pd.DataFrame, clim_weekly: pd.DataFrame | None,
                            out_path: Path) -> None:
    """Climatología mensual (todos los ámbitos) y semanal (solo si existe para el ámbito)."""
    m = clim_monthly.sort_values("month")
    obj = {
        "version": SCHEMA_VERSION,
        "ambito": ambito,
        "linea_base": CLIMATOLOGY["baseline"],
        "mensual": [{"mes": int(r["month"]), **rec}
                    for r, rec in zip(m.to_dict("records"), _records(m, CLIMATOLOGY_SPEC))],
        "semanal": None,
    }
    if clim_weekly is not None and len(clim_weekly):
        w = clim_weekly.sort_values("iso_week")
        obj["semanal"] = [{"semana_iso": int(r["iso_week"]), **rec}
                          for r, rec in zip(w.to_dict("records"), _records(w, CLIMATOLOGY_SPEC))]
    _write_json(obj, out_path)


def export_ranking_json(ambito: str, ranking: pd.DataFrame, out_path: Path) -> None:
    """Años ordenados por puesto (los incompletos, sin puesto, al final en orden cronológico)."""
    r = ranking.assign(_p=ranking["puesto"].fillna(1e9)).sort_values(["_p", "year"])
    obj = {
        "version": SCHEMA_VERSION,
        "ambito": ambito,
        "linea_base": CLIMATOLOGY["baseline"],
        "anios": _records(r, RANKING_SPEC),
    }
    _write_json(obj, out_path)


def _cell_aois(lat: float, lon: float) -> list[str]:
    """Ámbitos (rectángulos de settings.yaml) que contienen el centro de la celda (misma regla que climatology)."""
    return [name for name, (la0, la1, lo0, lo1) in CLIMATOLOGY["aois"].items()
            if la0 <= lat <= la1 and lo0 <= lon <= lo1]


def export_cells(monthly_cell: pd.DataFrame, out_dir: Path) -> dict:
    """
    cells_index.json (geometría ligera) + cells_{AAAA}.json (por año, solo celdas con focos > 0).
    Los meses del año sin ninguna fila en la tabla (p. ej. ene-jun 2002) se exportan como null.
    """
    cells = (monthly_cell[["cell", "lat_c", "lon_c"]].drop_duplicates("cell")
             .sort_values(["lat_c", "lon_c"], ascending=[False, True]))
    index = {
        "version": SCHEMA_VERSION,
        "tamano_celda": CELL_SIZE,
        "celdas": [{"id": c, "lat": round(la, 3), "lon": round(lo, 3), "ambitos": _cell_aois(la, lo)}
                   for c, la, lo in cells.itertuples(index=False)],
    }
    sizes = {"cells_index.json": _write_json(index, out_dir / "cells_index.json")}

    years = []
    for year, g in monthly_cell.groupby("year", sort=True):
        months_present = sorted(int(m) for m in g["month"].unique())
        quality = (g.drop_duplicates("month").set_index("month")["calidad"].to_dict())
        piv_n = g.pivot_table(index="cell", columns="month", values="count", aggfunc="sum")
        piv_f = g.pivot_table(index="cell", columns="month", values="frp", aggfunc="sum")
        tot_n, tot_f = piv_n.sum(axis=1), piv_f.sum(axis=1)
        keep = tot_n[tot_n.round() > 0].index
        celdas = {}
        for cell in keep:
            meses = [(_int(piv_n.at[cell, m]) if m in piv_n.columns and not _missing(piv_n.at[cell, m]) else 0)
                     if m in months_present else None for m in range(1, 13)]
            celdas[cell] = {"count": _int(tot_n[cell]), "frp": _int(tot_f[cell]), "meses": meses}
        obj = {
            "version": SCHEMA_VERSION,
            "anio": int(year),
            "tramo": _tramo_id(g["tramo"].iloc[0]),
            "meses_con_dato": [m in months_present for m in range(1, 13)],
            "calidad_meses": [_str(quality.get(m)) for m in range(1, 13)],
            "max_count": _int(tot_n.max()),
            "celdas": celdas,
        }
        name = f"cells_{int(year)}.json"
        sizes[name] = _write_json(obj, out_dir / name)
        years.append(int(year))
    return {"anios": years, "n_celdas": len(index["celdas"]), "bytes": sizes}


def export_meta_json(processed_dir: Path, ambitos: dict, files: dict, cell_years: list[int],
                     out_path: Path) -> None:
    """Leyenda, ámbitos, tramos, factores y el índice de archivos generados."""
    harm = json.loads((processed_dir / "harmonize_summary.json").read_text(encoding="utf-8"))
    factors = {"count": {}, "frp": {}}
    for f in harm["factores"]:
        key = "count" if f["metric"] == "count" else "frp"
        factors[key][f["season"]] = {"factor": round(f["factor"], 3),
                                     "ic_inf": round(f["ic_inf"], 3), "ic_sup": round(f["ic_sup"], 3)}
    est = HARMONIZE["estimated"]
    obj = {
        "version": SCHEMA_VERSION,
        "generado": date.today().isoformat(),
        "linea_base": CLIMATOLOGY["baseline"],
        "ambitos": ambitos,
        "categorias": [{"id": CATEGORY_IDS[c], "etiqueta": c[0].upper() + c[1:], "color": CATEGORY_COLORS[c],
                        "orden": i} for i, c in enumerate(CATEGORIES + [NO_DATA])],
        "tramos": [
            {"id": "estimado", "etiqueta": "Estimado (MODIS Aqua × factor)", "anios": [est[0], est[-1]]},
            {"id": "viirs_real", "etiqueta": "VIIRS real", "anios": [est[-1] + 1, None]},
        ],
        "fuentes": {
            "estimado": "Aqua × factor de temporada",
            "S-NPP": "VIIRS Suomi-NPP",
            "NOAA-20": "VIIRS NOAA-20 (respaldo de S-NPP)",
            "NOAA-21": "VIIRS NOAA-21",
            "sin dato": "Sin observación válida",
        },
        "calidades": {
            "ok": "Dato completo",
            "parcial": "Semana/mes con días fuera del rango de datos",
            "incompleto": "Mes con días sin dato o mezcla de fuentes con huecos",
            "relleno": "Semana VIIRS sin sensor válido, rellenada con Aqua × factor",
            "sin dato": "Sin observación válida (valor null)",
        },
        "temporadas": {k: [int(m) for m in v] for k, v in SEASONS.items()},
        "unidades": {"count": "focos de calor (equivalente VIIRS 375 m)", "frp": "MW (suma de FRP)"},
        "modelo": harm.get("modelo"),
        "factores": factors,
        "cobertura_banda": HARMONIZE["band_coverage"],
        "semana_inicio": harm.get("semana_inicio"),
        "semana_fin": harm.get("semana_fin"),
        "celdas_anios": cell_years,
        "archivos": files,
    }
    _write_json(obj, out_path)


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------
def run_export(processed_dir: Path, out_dir: Path, monthly_cell: pd.DataFrame | None) -> dict:
    """Paso 10: genera todos los archivos del frontend en out_dir (por defecto output/web/)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    anom_m = pd.read_csv(processed_dir / "anomalies_monthly.csv")
    anom_w = pd.read_csv(processed_dir / "anomalies_weekly.csv")
    clim_m = pd.read_csv(processed_dir / "climatology_monthly.csv")
    clim_w = pd.read_csv(processed_dir / "climatology_weekly.csv")
    ranks = pd.read_csv(processed_dir / "annual_ranking.csv")
    if "ambito" not in clim_w:
        clim_w = clim_w.assign(ambito="peru")

    files: dict[str, dict] = {}
    ambitos = {}
    for ambito in anom_m["ambito"].unique():
        bbox = CLIMATOLOGY["aois"].get(ambito)
        ambitos[ambito] = {
            "nombre": AMBITO_NAMES.get(ambito, ambito.capitalize()),
            "bbox": bbox,  # [lat_min, lat_max, lon_min, lon_max]; null = todo Perú
            "provisional": bbox is not None,
            "tiene_bandas": bool(anom_m.loc[anom_m["ambito"] == ambito, "count_inf"].notna().any()),
            "tiene_semanal": ambito == "peru",
        }
        for name, writer in [
            (f"calendar_{ambito}.json",
             lambda p: export_calendar_json(anom_m[anom_m["ambito"] == ambito], p)),
            (f"climatology_{ambito}.json",
             lambda p: export_climatology_json(ambito, clim_m[clim_m["ambito"] == ambito],
                                               clim_w[clim_w["ambito"] == ambito], p)),
            (f"ranking_{ambito}.json",
             lambda p: export_ranking_json(ambito, ranks[ranks["ambito"] == ambito], p)),
        ]:
            writer(out_dir / name)
            files[name] = {"vista": name.split("_")[0], "ambito": ambito}

    export_weekly_series_json(anom_w, out_dir / "series_weekly_peru.json")
    files["series_weekly_peru.json"] = {"vista": "series_weekly", "ambito": "peru"}

    cell_years: list[int] = []
    if monthly_cell is not None:
        info = export_cells(monthly_cell, out_dir)
        cell_years = info["anios"]
        files["cells_index.json"] = {"vista": "cells_index", "ambito": "peru"}
        files["cells_{anio}.json"] = {"vista": "cells", "ambito": "peru", "anios": cell_years}
        print(f"Celdas: {info['n_celdas']} celdas de {CELL_SIZE}°, {len(cell_years)} años")
    else:
        print("Aviso: no se encontró harmonized_monthly_cell; se omiten cells_*.json")

    export_regional_summary_csv(anom_m, out_dir / "regional_summary.csv")
    export_meta_json(processed_dir, ambitos, files, cell_years, out_dir / "meta.json")

    total = sum(p.stat().st_size for p in out_dir.glob("*.json"))
    print(f"Exportados {len(list(out_dir.glob('*.json')))} JSON ({total / 1024:.0f} KB) en {out_dir}")
    for p in sorted(out_dir.glob("*.json")):
        if not p.name.startswith("cells_") or p.name == "cells_index.json":
            print(f"  {p.name:28s} {p.stat().st_size / 1024:7.1f} KB")
    return {"archivos": sorted(p.name for p in out_dir.iterdir()), "bytes_json": total}
