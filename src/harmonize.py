"""
Módulo de armonización de series temporales (STUB).
Aplica el factor de escala o función de enlace calibrada a nivel agregado a la serie histórica 2002-2011.
Nunca se aplica a puntos calientes individuales crudos.
"""

from __future__ import annotations

import pandas as pd


def apply_harmonization(df_aggregated: pd.DataFrame, model_fit: dict, target_years: list[int]) -> pd.DataFrame:
    """
    STUB: Transforma conteos y FRP agregados de MODIS al equivalente VIIRS usando el modelo calibrado.

    Entradas:
        df_aggregated: DataFrame agregado (semanal o diario) que contiene datos MODIS históricos.
        model_fit: Coeficientes o modelo calibrado proveniente de calibration.py.
        target_years: Años a armonizar (ej. 2002 a 2011).
    Salidas:
        DataFrame con la serie temporal unificada y columnas armonizadas.
    """
    raise NotImplementedError("apply_harmonization no implementado aún.")
