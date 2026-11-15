# CLAUDE.md

Guía para sesiones de Claude Code en este repositorio. Complementa a [README.md](README.md) (uso y roles del equipo) y a [docs/decisiones.md](docs/decisiones.md) (decisiones metodológicas). Si algo aquí contradice esos documentos, verifica en el código y actualiza el que esté desfasado.

## Contexto
Proyecto para el **NASA Space Apps Challenge**: calendario y atlas de actividad de quema en Perú (caso de estudio: Cusco) con focos de calor de **NASA FIRMS**. El problema central es **armonizar MODIS (1 km, desde 2002) con VIIRS (375 m, desde 2012)**. VIIRS detecta unas 5–6 veces más focos que MODIS Aqua, así que se calibra una razón VIIRS/Aqua (GLM) en el período en que ambos coinciden y se aplica hacia atrás para obtener una serie única desde 2002.

Todo el proyecto (código, comentarios, docstrings, mensajes de CLI, documentación y commits) está **en español**. Mantén ese idioma.

## Puesta en marcha (Windows, PowerShell o Git Bash)
```powershell
python -m venv .venv                 # probado con Python 3.14
.\.venv\Scripts\activate
pip install -r requirements.txt pyarrow   # incluye statsmodels; pyarrow es opcional (sin él se guarda .csv.gz)
$env:PYTHONIOENCODING="utf-8"        # evita errores de acentos en la consola de Windows
```

### Datos crudos (`dataset/`, ignorado por git)
Son los CSV anuales por país del archivo público de FIRMS. Se descargan sin autenticación:
```
https://firms.modaps.eosdis.nasa.gov/data/country/{fuente}/{AAAA}/{fuente}_{AAAA}_Peru.csv
```
| fuente | años disponibles | carpeta local |
|---|---|---|
| `modis` (Terra y Aqua juntos; se separan con la columna `satellite`) | 2000– | `dataset/modis/` |
| `viirs-snpp` | 2012– | `dataset/snpp/` |
| `viirs-jpss1` (NOAA-20) | 2018– | `dataset/noaa20/` |
| `viirs-jpss2` (NOAA-21) | **no está** en el archivo por país (404 en 2023–2025, comprobado en nov-2026); habría que conseguirlo por la API de FIRMS | `dataset/noaa21/` (opcional) |

Ejemplo en Git Bash:
```bash
B=https://firms.modaps.eosdis.nasa.gov/data/country
mkdir -p dataset/{modis,snpp,noaa20}
for y in $(seq 2002 2024); do curl -sf -o dataset/modis/modis_${y}_Peru.csv $B/modis/$y/modis_${y}_Peru.csv; done
for y in $(seq 2012 2024); do curl -sf -o dataset/snpp/viirs-snpp_${y}_Peru.csv $B/viirs-snpp/$y/viirs-snpp_${y}_Peru.csv; done
for y in $(seq 2018 2024); do curl -sf -o dataset/noaa20/viirs-jpss1_${y}_Peru.csv $B/viirs-jpss1/$y/viirs-jpss1_${y}_Peru.csv; done
```
`io_firms.find_files` reconoce los nombres con la regex `^{prefijo}_(\d{4})_peru\.csv$` (sin distinguir mayúsculas). Una carpeta obligatoria (modis, snpp) que falte detiene el programa; las de NOAA se omiten con un aviso.

## Comandos
Se ejecutan **desde la raíz**: `python src/cli.py <comando>`. Los módulos de `src/` se importan entre sí como módulos de primer nivel (`from config import ...`), así que funcionan porque `src/` queda en `sys.path` al lanzar `src/cli.py`. Para importarlos desde un script o REPL, ejecuta desde `src/` o añade `src` a `sys.path`.

| Comando | Estado | Salidas |
|---|---|---|
| `audit [--years ...] [--all-years]` | Implementado | `output/reports/audit_*.csv`, `audit_*.png` (**versionados en git**: correrlo modifica archivos rastreados) |
| `build [--years ...] [--all-years]` | Implementado | `output/interim/daily_cell_sensor`, `weekly_sensor`, `weekly_cell_sensor` (.parquet), `build_summary.csv` |
| `calibrate` | Implementado (lee `output/interim/weekly_sensor`) | `output/processed/calibration_factors.csv`, `validation_*.csv`, `harmonization_factors.csv` (factor final), `calibration_summary.json`; `output/reports/calibration_validation.png` |
| `harmonize`, `climatology`, `export` | Vacíos (lanzan `NotImplementedError`) | — |

Sin `--years` ni `--all-years`, ambos comandos usan `years.min`–`years.max` de `config/settings.yaml` (2012–2017). Para que los pasos posteriores tengan 2002–2024, ejecuta `build --all-years` (tarda ~1 min con los 43 archivos).

No hay tests ni linter configurados. Para validar un cambio, ejecuta `build`/`audit` y compara totales. Por ejemplo, `count.sum()` debe ser idéntico en las tablas diaria y semanales.

## Arquitectura y flujo de datos
```
dataset/*.csv
  └─ io_firms.load ─► cleaning.standardize   (UTC→hora local UTC-5, dedup, type==0, confianza low/medium/high, celda 0.25°)
       ├─ audit.run_audit         → output/reports/
       └─ aggregate.aggregate_daily → daily_cell_sensor   (día local × celda × sensor)
            └─ aggregate.aggregate_weekly(level="national"|"cell") → weekly_sensor / weekly_cell_sensor
                 └─ calibration.run_calibration → output/processed/harmonization_factors.csv
                      └─ harmonize (2002–2011) → climatology → export_web   [pendientes]
```
- [src/config.py](src/config.py): lee `config/settings.yaml` y expone constantes (rutas absolutas desde la raíz, `YEAR_MIN/MAX`, `WINDOWS`, `SEASONS`, `CELL_SIZE`, umbrales de alertas, `SOURCES`).
- [src/yaml_loader.py](src/yaml_loader.py): usa PyYAML si está instalado. Si no, usa un parser propio que **solo admite un nivel de anidamiento** (sección → clave: escalar o lista `[a, b]`). Mantén `settings.yaml` dentro de ese formato.
- [src/cleaning.py](src/cleaning.py): funciones puras, sin acceso a disco.
- [src/legacy/firms_pipeline.py](src/legacy/firms_pipeline.py): el monolito original, solo como referencia. No lo modifiques ni lo importes.
- [explainer/index.html](explainer/index.html): página educativa que funciona como **hoja de ruta**. El array `STEPS` (pasos 0–9) describe objetivo, entradas, salidas, errores típicos y código orientativo de cada etapa (GLM con statsmodels, validación, aplicación del factor, serie única, climatología). Consúltalo antes de implementar un stub.

### Esquemas de las tablas intermedias
- **daily_cell_sensor**: `local_date, cell, lat_c, lon_c, sensor, family, count, count_with_low, total_frp, total_frp_with_low`. Solo contiene filas con detecciones (no hay ceros).
  - `count` y `total_frp` excluyen la confianza baja; las variantes `*_with_low` la incluyen.
  - `cell` es `"{lat_c:.3f}_{lon_c:.3f}"`, con el centro de la celda.
  - `sensor` ∈ {Aqua, Terra, SNPP, NOAA20, NOAA21}; `family` ∈ {MODIS, VIIRS}.
- **weekly_sensor** (semana × sensor, todo Perú): las métricas anteriores más `active_cells`, `days_with_data`, `week` (lunes), `iso_year`, `iso_week`, `month` y `season`.
- **weekly_cell_sensor** (semana × celda × sensor): igual, pero con `active_days` en lugar de `active_cells`.
- Reglas de las tablas semanales:
  - Usan la semana ISO en hora local. El `month` es el del jueves de la semana. Filtra las ventanas con `iso_year`.
  - Incluyen **ceros explícitos**. A nivel nacional, cada sensor tiene todas las semanas entre su primera y su última semana con datos. A nivel de celda, cada semana combina las celdas con alguna detección (de cualquier sensor) con todos los sensores que operaban esa semana.
  - `days_with_data` cuenta los días de la semana en que el sensor tuvo al menos una detección en todo el dominio. Si vale 0, la semana probablemente no tiene observaciones, no cero fuegos. Filtra esas semanas al calibrar.
  - `season` se define en `settings.yaml` → `seasons`: alta = ago–sep (~60–65 % de las detecciones), media = jun–jul y oct–nov, baja = dic–may.

## Reglas metodológicas (no romper)
1. **Aqua es la referencia de MODIS.** Pasa a ~13:30, igual que VIIRS. **Terra** (~10:30, detecta ~20 % de lo que detecta Aqua) queda fuera de la calibración y solo sirve como análisis de sensibilidad.
2. Calibración en **2012–2017**, validación en **2018–2022** y reajuste final en **2012–2022** (`settings.yaml` → `windows`). La ventana final no llega más allá de 2022 porque **Aqua deriva desde 2023** (pasa a las 13:51 en 2023 y a las 14:16 en 2024). Elige el modelo por su error en validación, no por su ajuste en calibración (`select_model`: el más simple salvo mejora de MAE > 5 %).
3. Los GLM van **de menos a más complejo**: (A) un solo factor; (B) un factor por temporada; (C) temporada + zona. Usa Poisson con errores agrupados por semana, o binomial negativa si hay sobredispersión, y Gamma/Tweedie para el FRP. El factor es `exp(β)` con su IC 95 %.
4. El factor se aplica **solo a series agregadas** (celda/semana o región/semana) y **nunca a puntos individuales**. Al aplicarlo hacia atrás se usa solo el factor, no el efecto fijo de semana, y la incertidumbre se propaga con bandas `ic_inf`/`ic_sup`.
5. **No omitas las semanas con cero detecciones**, porque sesgan el modelo hacia arriba.
6. En la serie única, marca 2002–2011 como "estimado" y 2012 en adelante como "VIIRS real".

## Estado actual y pendientes
- Hecho: ingesta, limpieza, auditoría, agregación diaria y semanal, y calibración GLM (detalles en las decisiones 7–11 de `docs/decisiones.md`).
- Resultado de la calibración (conteos, tabla nacional): el modelo elegido es **B (por temporada)**. Factores finales 2012–2022: alta ≈ 5.15, media ≈ 6.69, baja ≈ 8.84. FRP: 1.84 / 2.23 / 2.92. Validación 2018–2022: error total −1.3 %, corr 0.91, MAE relativo 22 %. 2020 es el peor año: los picos de agosto que Aqua detecta mal son un límite del sensor, no un error de datos.
- `calibration.paired_weeks` excluye las semanas con Aqua sin datos o con VIIRS < `MIN_TARGET_DAYS` (6) días. Los apagones de S-NPP (jul–ago 2022, jul 2024) caen ahí; en el futuro se podrían rellenar con NOAA-20.
- Referencias (2012–2017, Perú, conteos limpios):
  - S-NPP/Aqua ≈ 5.1–6.4 por año (≈ 5.76 en el agregado semanal).
  - Terra/Aqua ≈ 0.18–0.27.
  - Aqua y S-NPP pasan a ~13:30 todos los años; Terra a ~10:30.
- Pendiente, en orden:
  1. `harmonize.apply_harmonization`: Aqua 2002–2011 × factor de temporada a partir de `harmonization_factors.csv`, con bandas IC, más VIIRS real desde 2012.
  2. `climatology` (mediana y percentiles por semana del año, anomalías).
  3. `export_web` (JSON/CSV para el frontend).
  4. Conectar los comandos en `cli.py`.
- Sin definir todavía: la variable **zona** del modelo C (p. ej., Andes/Amazonía) y el **recorte del AOI de Cusco**.
- Los datos de 2025 ya están en el archivo de FIRMS, pero aún no se descargaron (lo descargado llega hasta 2024). El explainer menciona que S-NPP termina el 2-nov-2026; está por verificar.

## Equipo y convenciones de git
- Hay 5 personas, cada una dueña de un grupo de módulos (ver la sección 5 del README) para evitar conflictos de git. Mantén las firmas de las funciones stub, porque son los contratos entre integrantes.
- Commits en español con formato conventional: `tipo(ámbito): descripción en infinitivo`. Ejemplo: `feat(aggregate): implementar agregación semanal ISO con ceros explícitos`.
- No versionar `dataset/`, `output/interim/`, `*.parquet` ni `*.csv.gz`. `output/reports/` **sí** se versiona.
