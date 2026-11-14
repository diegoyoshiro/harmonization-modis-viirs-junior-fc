"""
Módulo de climatología y detección de anomalías (STUB).
Calcula la línea base histórica multianual (mediana, percentiles) y anomalías de la serie armonizada.
"""

from __future__ import annotations

import pandas as pd


def compute_baseline(df_harmonized: pd.DataFrame, baseline_years: list[int]) -> pd.DataFrame:
    """
    STUB: Calcula estadísticas climatológicas de referencia por semana del año y celda geográfica.

    Entradas:
        df_harmonized: Serie temporal armonizada unificada.
        baseline_years: Ventana de referencia climatológica.
    Salidas:
        DataFrame con mediana, percentil 10, percentil 90 y umbrales de severidad por celda/semana.
    """
    raise NotImplementedError("compute_baseline no implementado aún.")


def compute_anomalies(df_harmonized: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    """
    STUB: Evalúa desviaciones relativas y absolutas respecto a la climatología histórica.

    Entradas:
        df_harmonized: Serie armonizada.
        baseline: Estadísticas de referencia calculadas por compute_baseline.
    Salidas:
        DataFrame con anomalías y categorías de actividad de quema.
    """
    raise NotImplementedError("compute_anomalies no implementado aún.")
