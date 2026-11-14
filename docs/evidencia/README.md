# Evidencia y Diagnósticos de Calibración / Auditoría

Esta carpeta contiene figuras, diagnósticos y artefactos de verificación empírica generados durante el análisis de calidad y armonización del dataset NASA FIRMS para Perú:

1. **`harmonization_series_scatter.png`**: Gráficos de dispersión y series comparativas preliminares entre sensores (Aqua vs. S-NPP) correspondientes a las pruebas de modelado de solapamiento.
2. **Resultados de auditoría 2012–2017**:
   - Al ejecutar `python src/cli.py audit`, los reportes anuales consolidados, razones entre sensores y diagnósticos de hora de paso orbital se depositan en `output/reports/`.
   - Para conservar la evidencia de una auditoría histórica específica o incorporar capturas adicionales de validación científica, copiar los archivos resultantes a esta carpeta documentando la fecha y versión en este archivo.
