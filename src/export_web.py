"""
Módulo de exportación para la interfaz web (STUB).
Genera estructuras JSON y CSV optimizadas para visualización en el frontend estático.
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd


def export_calendar_json(df_anomalies: pd.DataFrame, out_path: Path) -> None:
    """
    STUB: Exporta el calendario de actividad de quema en formato JSON estructurado para la web.

    Entradas:
        df_anomalies: DataFrame con serie temporal y anomalías.
        out_path: Ruta del archivo JSON de destino.
    Salidas:
        Escribe archivo JSON listo para consumo estático.
    """
    raise NotImplementedError("export_calendar_json no implementado aún.")


def export_regional_summary_csv(df_anomalies: pd.DataFrame, out_path: Path) -> None:
    """
    STUB: Exporta resumen de métricas clave por región/celda en CSV ligero.

    Entradas:
        df_anomalies: DataFrame con métricas procesadas.
        out_path: Ruta del archivo CSV de destino.
    Salidas:
        Escribe archivo CSV.
    """
    raise NotImplementedError("export_regional_summary_csv no implementado aún.")
