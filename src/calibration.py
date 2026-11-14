"""
Módulo de calibración empírica (STUB).
Ajuste de modelos lineales generalizados (GLM) para relacionar MODIS (Aqua) con VIIRS (S-NPP)
en ventanas temporales de solapamiento y validación con periodos retenidos.
"""

from __future__ import annotations

import pandas as pd


def train_glm_weekly(df_weekly: pd.DataFrame, calibration_years: list[int]) -> dict:
    """
    STUB: Calibra el modelo GLM semanal entre Aqua y S-NPP en los años de solapamiento.

    Entradas:
        df_weekly: DataFrame semanal con columnas para MODIS (Aqua) y VIIRS (SNPP).
        calibration_years: Lista de años a utilizar para entrenamiento (ej. [2012, 2017]).
    Salidas:
        Diccionario con coeficientes del modelo, métricas de ajuste (AIC, pseudo-R2, dispersión).
    """
    raise NotImplementedError("train_glm_weekly no implementado aún.")


def validate_glm(model_fit: dict, df_weekly: pd.DataFrame, validation_years: list[int]) -> pd.DataFrame:
    """
    STUB: Evalúa el desempeño predictivo del GLM sobre años retenidos no vistos en el ajuste.

    Entradas:
        model_fit: Resultado de train_glm_weekly.
        df_weekly: DataFrame semanal de prueba.
        validation_years: Lista de años para testeo ciego (ej. [2018, 2022]).
    Salidas:
        DataFrame con métricas de validación (RMSE, MAE, sesgo, cobertura por celda/semana).
    """
    raise NotImplementedError("validate_glm no implementado aún.")
