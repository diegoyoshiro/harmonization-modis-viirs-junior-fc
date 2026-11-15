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

### Datos crudos (`dataset/`, **versionado en git** desde nov-2026: 47 CSV)
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
for y in $(seq 2012 2026); do curl -sf -o dataset/snpp/viirs-snpp_${y}_Peru.csv $B/viirs-snpp/$y/viirs-snpp_${y}_Peru.csv; done
for y in $(seq 2018 2026); do curl -sf -o dataset/noaa20/viirs-jpss1_${y}_Peru.csv $B/viirs-jpss1/$y/viirs-jpss1_${y}_Peru.csv; done
```
**Lo descargado hoy:** MODIS 2002–2024; S-NPP 2012–2026; NOAA-20 2018–2026. No hay MODIS 2025–2026, así que desde 2025 la serie es solo VIIRS (no hay Aqua para rellenar huecos).

#### Datos NRT de 2026 (preliminares)
El CSV del año en curso mezcla dos productos. Se distinguen con la columna **`version`** del CSV:
| archivo | `version = 2` (estándar) | `version = 2.0NRT` (Near Real-Time) |
|---|---|---|
| `viirs-snpp_2026_Peru.csv` | 01-ene al 31-jul-2026 (11 349 filas) | 01-ago al 01-nov-2026 (43 565 filas; S-NPP terminó el 2-nov) |
| `viirs-jpss1_2026_Peru.csv` | 01-ene al 31-jul-2026 (12 648 filas) | 01-ago al 15-nov-2026 (44 767 filas) |

- El NRT se publica a las ~3 h, con geolocalización y calibración provisionales. FIRMS lo reemplaza por el estándar con meses de retraso, así que estos valores **cambiarán** cuando se vuelva a descargar el CSV.
- **Regla: toda semana, mes o celda que incluya al menos un día NRT es `preliminar`** en las salidas de `harmonize`, `climatology` y `export`.
  - Se marca con un booleano aparte, `preliminar`, no con un nuevo valor de `calidad`: una semana puede ser `ok` y `preliminar` a la vez.
  - El criterio es el producto (`version` contiene `NRT`), no una fecha fija. Así la marca se mueve sola cuando FIRMS reemplace el NRT por el estándar.
  - El NRT **nunca entra** en la calibración (ventanas ≤ 2022) ni en la línea base de la climatología (2003–2024). Solo se muestra, con su anomalía frente a la línea base, marcado como preliminar.
  - Nov-2026 es además un mes incompleto (S-NPP hasta el día 1, NOAA-20 hasta el 15), así que su `calidad` es `incompleto`.
- **Implementado** (nov-2026):
  1. `cleaning.standardize`: `is_nrt` = `version` contiene `NRT`.
  2. `aggregate`: columna `nrt_count` (detecciones NRT, con baja confianza) en la tabla diaria y en las semanales. Está en `aggregate.METRICS` solo para sumarse; no es una métrica de fuego.
  3. `harmonize.nrt_start`: primer día con NRT de cada sensor (hoy S-NPP y NOAA-20, 2026-08-01). Desde ese día todo lo del sensor es preliminar, aunque algún día no tenga focos. Columnas `preliminar` en `harmonized_weekly` (y `_cell`; la semana toca el tramo NRT del sensor usado), `preliminar` + `dias_preliminar` en `harmonized_monthly` (y `_cell`), `weeks_preliminar` en `harmonized_annual`, y `nrt_inicio` + `semanas_preliminares` en `harmonize_summary.json`. Hoy son 15 semanas (2026-07-27 a 2026-11-02) y 4 meses (ago–nov-2026).
  4. `climatology`: la marca pasa a `anomalies_*`, a las áreas (`region_monthly`) y a `annual_ranking` (`preliminar` del año). En `calendar_*.png`, los meses llevan una "p" y un borde punteado, y el año, " p". En `climatology_weekly_peru.png`, el tramo NRT va punteado.
  5. `export` (esquema 1.2): `preliminar` en `calendar_*`, `series_weekly_*` y `ranking_*`; `dias_preliminar` en el calendario; `preliminar_meses` en `cells_{AAAA}.json`; bloque `preliminar` en `meta.json`; `meses_preliminares` en `regional_summary.csv`.
  - La marca no cambia ningún valor: la serie es idéntica con y sin ella.
`io_firms.find_files` reconoce los nombres con la regex `^{prefijo}_(\d{4})_peru\.csv$` (sin distinguir mayúsculas). Una carpeta obligatoria (modis, snpp) que falte detiene el programa; las de NOAA se omiten con un aviso.

## Comandos
Se ejecutan **desde la raíz**: `python src/cli.py <comando>`. Los módulos de `src/` se importan entre sí como módulos de primer nivel (`from config import ...`), así que funcionan porque `src/` queda en `sys.path` al lanzar `src/cli.py`. Para importarlos desde un script o REPL, ejecuta desde `src/` o añade `src` a `sys.path`.

| Comando | Estado | Salidas |
|---|---|---|
| `audit [--years ...] [--all-years]` | Implementado | `output/reports/audit_*.csv`, `audit_*.png` (**versionados en git**: correrlo modifica archivos rastreados) |
| `build [--years ...] [--all-years]` | Implementado | `output/interim/static_mask`, `daily_cell_sensor`, `weekly_sensor`, `weekly_cell_sensor` (.parquet; malla de resolución variable, ver abajo), `build_summary.csv` |
| `calibrate` | Implementado (lee `output/interim/weekly_sensor`) | `output/processed/calibration_factors.csv`, `validation_metrics.csv`, `validation_by_year.csv`, `validation_monthly.csv`, `validation_noaa20_snpp.csv`, `harmonization_factors.csv` (factor final), `calibration_summary.json`; `output/reports/calibration_validation.png` |
| `validate` | Implementado (lee `calibration_factors.csv` y `weekly_sensor`) | Rehace solo las tablas `validation_*.csv` |
| `harmonize` | Implementado (lee `weekly_sensor`, `weekly_cell_sensor` y los factores de `calibrate`) | `output/processed/harmonized_weekly.csv` (serie única nacional), `harmonized_weekly_cell` (.parquet), `harmonized_annual.csv`, `harmonization_bands.csv`, `harmonization_backcast_check.csv`, `harmonize_summary.json`, `prediction_vs_snpp_*.csv` (MODIS × factor vs S-NPP 2012–2024), `harmonized_monthly.csv` + `harmonized_monthly_cell` (serie mensual desde la tabla diaria) y `harmonization_bands_monthly.csv`; `output/reports/harmonized_series.png`, `prediction_vs_snpp.png` |
| `climatology` | Implementado (lee `harmonized_weekly.csv`, `harmonized_monthly.csv`, `harmonized_monthly_cell`) | `output/processed/climatology_monthly.csv`, `climatology_weekly.csv`, `anomalies_monthly.csv`, `anomalies_weekly.csv`, `annual_ranking.csv`, `climatology_summary.json`; `output/reports/calendar_peru.png`, `calendar_cusco.png`, `climatology_weekly_peru.png` |
| `export` | Implementado (lee las salidas de `harmonize` y `climatology`) | `output/web/`: `meta.json`, `calendar_{ambito}.json`, `series_weekly_peru.json`, `climatology_{ambito}.json`, `ranking_{ambito}.json`, `cells_index.json`, `cells_{AAAA}.json`, `regional_summary.csv`. Contrato en [docs/frontend_datos.md](docs/frontend_datos.md) |

Sin `--years` ni `--all-years`, ambos comandos usan `years.min`–`years.max` de `config/settings.yaml` (2012–2017). Para que los pasos posteriores tengan 2002–2024, ejecuta `build --all-years` (tarda ~1 min con los 43 archivos).

No hay tests ni linter configurados. Para validar un cambio, ejecuta `build`/`audit` y compara totales. Por ejemplo, `count.sum()` debe ser idéntico en las tablas diaria y semanales.

## Arquitectura y flujo de datos
```
dataset/*.csv
  ├─ io_firms.collect_static_points ─► cleaning.build_static_mask → static_mask   (todos los años, siempre)
  └─ io_firms.load ─► cleaning.standardize   (UTC→hora local UTC-5, dedup, type==0, confianza low/medium/high, celda 0.25°)
       │               + cleaning.flag_static (is_static_loc, solo en build)
       ├─ audit.run_audit         → output/reports/   (sin máscara: audita el dato crudo)
       └─ aggregate.aggregate_daily → daily_cell_sensor   (día local × celda × sensor; type==0 y fuera de la máscara)
            └─ aggregate.aggregate_weekly(level="national"|"cell") → weekly_sensor / weekly_cell_sensor
                 └─ calibration.run_calibration → output/processed/harmonization_factors.csv
                      └─ harmonize.run_harmonization → harmonized_weekly (+ _cell, _annual)
                           └─ climatology.run_climatology → anomalies_* / climatology_* / annual_ranking
                                └─ export_web.run_export → output/web/*.json
```
- [src/config.py](src/config.py): lee `config/settings.yaml` y expone constantes (rutas absolutas desde la raíz, `YEAR_MIN/MAX`, `WINDOWS`, `SEASONS`, `OUTAGES`, `STATIC_MASK`, `CELL_SIZE`, umbrales de alertas, `SOURCES`).
- [src/yaml_loader.py](src/yaml_loader.py): usa PyYAML si está instalado. Si no, usa un parser propio que **solo admite un nivel de anidamiento** (sección → clave: escalar o lista `[a, b]`). Mantén `settings.yaml` dentro de ese formato.
- [src/cleaning.py](src/cleaning.py): funciones puras, sin acceso a disco.
- [src/legacy/firms_pipeline.py](src/legacy/firms_pipeline.py): el monolito original, solo como referencia. No lo modifiques ni lo importes.
- [explainer/index.html](explainer/index.html): página educativa que funciona como **hoja de ruta**. El array `STEPS` (pasos 0–9) describe objetivo, entradas, salidas, errores típicos y código orientativo de cada etapa (GLM con statsmodels, validación, aplicación del factor, serie única, climatología). Consúltalo antes de implementar un stub.

### Esquemas de las tablas intermedias
- **Malla única de resolución variable** (`settings.yaml` → `processing`; columnas en `cleaning.CELL_COLS`). Todas las tablas por celda (`daily_cell_sensor`, `weekly_cell_sensor`, `harmonized_*_cell`) llevan:
  - `cell`, `lat_c`, `lon_c`: la **celda del mapa**. Mide `cell_size_deg` = 0.25° (~28 km) antes de 2012 y `fine_cell_size_deg` = 0.1° (~11 km) desde el 1-ene de `fine_cell_from_year` = 2012 (fecha local; la era VIIRS 375 m). Se aplica a todos los sensores, también a Aqua desde 2012.
  - `cell_deg` (0.25 o 0.1): **distingue las dos épocas**. Los ids no chocan: los centros de 0.25° terminan en .125/.375/.625/.875 y los de 0.1°, en .x5.
  - `cell_025`, `lat_025`, `lon_025`: la **celda de análisis de 0.25°**, en todos los años. Las áreas (Cusco, `climatology.region_monthly`) se suman con su centro, para que 2002–2011 y 2012+ tengan los mismos bordes. `active_cells` de `weekly_sensor` también la usa.
  - Como 0.1 no divide a 0.25, una celda de 0.1° que cruza el borde de una de 0.25° se **parte en dos filas** (2165 de las 8095 celdas finas de 2012–2026). Sumar por `cell` da el total exacto de la celda del mapa; sumar por `cell_025`, el de la celda de análisis. El total nacional no cambia.
  - Comprobado: la suma por `cell_025` reproduce la tabla anterior de 0.25° (salvo los 41 focos de las 4 celdas nuevas de la máscara); suma de celdas = total nacional en las tablas semanal y mensual; Cusco: 0 de 270 meses cambian de categoría.
  - Cuidado al comparar celdas entre 2011 y 2012: una de 0.25° tiene 6.25 veces el área de una de 0.1°. En el mapa conviene mostrar densidad (focos/100 km²).
  - Con la malla fina, `weekly_cell_sensor` pasa de 0.87 a 1.83 M filas y los `cells_{AAAA}.json` de 2012+ pesan ~300 KB cada uno (en total, ~6 MB para el mapa).
- **static_mask**: `key, lat_c, lon_c, n_years, n_detections, sensors, types`. Una fila por celda estática de 0.01° (sin el margen; el margen se añade al aplicarla).
- **daily_cell_sensor**: `local_date, cell, lat_c, lon_c, sensor, family, count, count_with_low, total_frp, total_frp_with_low`. Solo contiene filas con detecciones (no hay ceros).
  - `count` y `total_frp` excluyen la confianza baja; las variantes `*_with_low` la incluyen.
  - `cell` es `"{lat_c:.3f}_{lon_c:.3f}"`, con el centro de la celda.
  - `sensor` ∈ {Aqua, Terra, SNPP, NOAA20, NOAA21}; `family` ∈ {MODIS, VIIRS}.
- **weekly_sensor** (semana × sensor, todo Perú): las métricas anteriores más `active_cells`, `days_with_data`, `week` (lunes), `iso_year`, `iso_week`, `month`, `season` e `in_outage` (True si la semana se solapa con un apagón de `settings.yaml` → `outages`).
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
- Hecho: ingesta, limpieza, máscara de fuentes estáticas, auditoría, agregación diaria y semanal, y calibración GLM (detalles en las decisiones 7–12 de `docs/decisiones.md`).
- Parámetros de `calibration.py`: referencia `Aqua`, objetivo `SNPP`; Poisson para conteos y Tweedie (var_power 1.5) para FRP; errores agrupados por semana; `MIN_TARGET_DAYS = 6`; `MIN_IMPROVEMENT_PCT = 5.0`. NOAA-20 no entra al GLM: se usa como validación externa en `validation.py` (`validation_by_year.csv`, Aqua × factor de calibración vs S-NPP y vs NOAA-20 por año) y como control (`validation_noaa20_snpp.csv`). `validation.py` importa `paired_weeks`/`predict_target` de `calibration.py`; `run_calibration` importa `validation` dentro de la función para evitar el ciclo.
- Resultado de la calibración (conteos, tabla nacional): el modelo elegido es **B (por temporada)**. Factores finales 2012–2022 (con máscara): alta ≈ 4.97, media ≈ 6.66, baja ≈ 8.94. FRP: 1.78 / 2.22 / 2.99. Validación 2018–2022: error total +3.8 %, corr 0.98, MAE relativo 20 %. En FRP el modelo sobreestima ~+12 % en validación (menos fiable que los conteos). Excluir el apagón de Aqua subió la correlación de 2020 de 0.74 a 0.97.
- `calibration.paired_weeks` excluye:
  - las semanas con `in_outage`, que vienen de apagones documentados en `settings.yaml` → `outages`: Aqua del 16-ago al 2-sep-2020 (falla del FMU) y S-NPP del 27-jul al 10-ago-2022;
  - las semanas con Aqua sin datos;
  - las semanas con VIIRS < `MIN_TARGET_DAYS` (6) días.
- **Fuentes**: guías de usuario NASA que nos pasó el usuario: MODIS C6 Active Fire rev. B/C y VIIRS C2 Burned Area v1.1. Puntos relevantes:
  - Confianza MODIS: <30 baja, 30–79 nominal, ≥80 alta (coincide con `cleaning.py`).
  - `type`: 0 vegetación, 1 volcán, 2 fuente estática, 3 offshore.
  - Las series de MODIS con intervalos < ~8 días tienen sesgo de muestreo (por eso trabajamos por semana).
  - Los datos NRT no sirven para series largas. Todos los CSV descargados son estándar **salvo ago–nov de 2026**, que es NRT (ver "Datos NRT de 2026").
- **Versiones mezcladas de MODIS en FIRMS** (decisión 12): `6.2` en 2002–2017, `6.03` en 2018–2022 y `61.03` en 2023–24. El tipado de fuentes estáticas mejora desde 2018, así que antes de 2018 hay ~1–2 % de fuentes estáticas contadas como vegetación.
  - **Corregido con la máscara de fuentes estáticas** (`settings.yaml` → `static_mask`): celdas de 0.01° con `type` 1/2 en ≥ 2 años (de cualquier sensor), más un margen de ±1 celda, excluidas de todos los años. Quita el 1.3–1.5 % de Aqua antes de 2018 y el 0.8 % después; a S-NPP, el ~1.5 % en todos los años.
  - Su efecto en el factor es mínimo (≤ 1 %; la temporada baja sube a +1.1 %). Su valor está en limpiar la serie 2002–2011 y la climatología.
  - Si cambias sus parámetros, vuelve a correr `build --all-years` y `calibrate`.
- **S-NPP dejó de entregar datos el 2-nov-2026 a las 15:40 UTC** (blog Earthdata/LANCE, nov-2026). La serie VIIRS "real" debe continuar con NOAA-20 (y NOAA-21). NOAA-20/S-NPP ≈ 1.00 (0.92–1.05 por año) en 2018–2024, lo que respalda el empalme.
- Referencias (2012–2017, Perú, conteos limpios):
  - S-NPP/Aqua ≈ 5.1–6.4 por año (≈ 5.76 en el agregado semanal).
  - Terra/Aqua ≈ 0.18–0.27.
  - Aqua y S-NPP pasan a ~13:30 todos los años; Terra a ~10:30.
- Pendiente, en orden:
  1. ~~`harmonize`~~ **hecho** (decisión 13 de `docs/decisiones.md`). Reglas implementadas:
     - Tramo `estimado` = `iso_year` 2002–2011 (`settings.yaml` → `harmonize.estimated`): Aqua × factor de temporada del modelo elegido (`calibration_summary.json` → `chosen_model`).
     - Desde 2012, VIIRS real por semana: S-NPP si ≥ 6 días y sin `in_outage`; si no, NOAA-20 (luego NOAA-21); si ningún VIIRS sirve, Aqua × factor con `calidad = relleno` (4 semanas de 2012).
     - NaN (`fuente = sin dato`): semanas con Aqua de 0 días o solapadas con `harmonize.aqua_gaps` (lista plana de pares inicio, fin). Hoy: 2002-07-29, 2002-08-05 y 2010-02-01 (Aqua y Terra en 0 toda la semana).
     - La serie va de 2002-07-01 (semana `parcial`) a la última semana con algún VIIRS de 7 días. Con los datos hasta 2024 era 2024-12-23; con 2026 llegará a noviembre de 2026, y las últimas semanas serán NRT y `preliminar`. Hay que volver a correr `build --all-years` → `calibrate` → `harmonize` → `climatology` → `export`.
     - Columnas `tramo`, `fuente` ∈ {estimado, S-NPP, NOAA-20, NOAA-21, sin dato} y `calidad` ∈ {ok, parcial, relleno, sin dato}.
     - Bandas: `*_ic_inf/sup` (IC del factor) y `*_inf/sup` (banda de predicción semanal del 90 %, cuantiles de observado/predicho por temporada en validación, fuera de muestra). Cubre 88–90 % de las semanas en 2023–2024 (S-NPP y NOAA-20). Total anual: razón anual mín./máx. de validación (conteo 0.92–1.05; FRP 0.81–1.00, el FRP estimado tiene un sesgo de ~+12 %).
     - Por celda solo hay bandas IC del factor; la suma de celdas coincide con la serie nacional.
     - Pendiente: modelo C (zona) y usarlo en la serie por celda/Cusco.
  2. ~~`climatology`~~ **hecho** (decisión 14). Línea base 2003–2024 (`settings.yaml` → `climatology.baseline`) por mes y por semana ISO (53 → 52); anomalías con percentil empírico y semáforo de 6 categorías (paleta PuOr, apta para daltonismo); `categoria_incierta` si la banda del valor estimado cambia la categoría (89 % de los meses estimados, pero 12 de los 14 meses extremos siguen ≥ "por encima" con la banda inferior). Áreas de interés = rectángulos `aoi_*` en `settings.yaml`; `aoi_cusco` es **provisional**. La climatología de un área se calcula después de sumar sus celdas, nunca sumando percentiles de celdas.
     - Limitación vista en Cusco: en meses de lluvia Aqua suele ver 0 focos, y 0 × factor = 0, mientras VIIRS ve 5–60. Las anomalías "por debajo" de ene–abr en 2002–2011 en áreas chicas son en parte artefacto del sensor.
  3. ~~`export_web`~~ **hecho**: formato A (un JSON por vista) en `output/web/`; contrato en `docs/frontend_datos.md` (`SCHEMA_VERSION` en `export_web.py`: súbelo si cambias campos). Reglas: `null` = sin dato (nunca 0), ids de categoría sin acentos (`muy_por_debajo` … `maximo`, `sin_dato`), anomalía y percentil en `null` cuando `cat = sin_dato`; en el mapa no hay semáforo por celda. Falta: serie/climatología semanal de Cusco.
- **Factores GLM calculados**: A y B, para conteo y FRP, en calibración (2012–2017) y reajuste final de B (2012–2022). **Faltan**:
  - C (temporada + zona);
  - factores por celda o región (solo hay factor nacional);
  - binomial negativa como control de robustez (dispersión de Pearson 9–15, ya cubierta por los errores agrupados);
  - las variantes `*_with_low`;
  - Terra como análisis de sensibilidad.
- **Las bandas IC del factor no bastan para la serie**: el IC del factor es de ±6 %, pero el error semanal en validación ronda el 20 % (MAE relativo) y las bandas cubren solo el 19 % de las semanas de validación. `harmonize` ya lo hace con cuantiles empíricos de observado/predicho en validación (`harmonization_bands.csv`).
- Sin definir todavía: el **recorte del AOI de Cusco**. La zona del modelo C tiene una propuesta (ver abajo).

### Huecos de datos (revisados contra otros sensores)
FIRMS solo publica detecciones, así que un día sin focos puede ser nublado, sin fuego o sin dato. Se cruzó cada racha de ≥ 4 días sin focos con S-NPP/NOAA-20 (desde 2012) y con Terra (antes).
- **Aqua, 71 rachas.** El 85 % empieza entre enero y abril (lluvias: 2–4 focos/día). Con 1–2 focos esperados en el día, Aqua marca 0 el 54 % de los días, así que se tratan como **ceros reales**. Enero–abril es solo el 3.8 % del total anual de Aqua.
- **Faltas reales de dato de Aqua** (no están en `outages`):
  - **31-mar al 16-abr-2022**: 17 días con 0 focos, cuando S-NPP vio 299 (~33 esperados en Aqua). Excluirlo cambia el factor de la temporada baja solo −0.3 % (conteo) y −0.5 % (FRP). Agregarlo a `outages` es opcional.
  - **30-jul al 7-ago-2002**: 9 días en temporada alta, al inicio de los datos de Aqua (Terra vio 31 focos, con una mediana de 53 en esas fechas). Faltan ~640 focos (200–1500), así que **jul–dic de 2002 quedaría ~10 % bajo**. En `harmonize`, esas semanas deben quedar como **NaN ("sin dato")**, no como cero.
- **S-NPP 2024**, huecos no documentados por NASA: 29-may al 4-jun, 9 al 16-jul y 23 al 29-jul. NOAA-20 vio 1000–2500 focos en cada uno, así que el hueco es del sensor. No afectan la calibración, pero en `harmonize` hay que usar NOAA-20 en esas semanas.
- Limitación: `OUTAGES` admite **un solo período por sensor** (`{sensor: (inicio, fin)}`). Para registrar varios hay que cambiar el formato en `config.py`/`settings.yaml` y respetar el parser de un nivel.
- Aqua empieza el 4-jul-2002: la serie armonizada arranca ahí.

### Modelo C: variación espacial y datos de zona
- **La razón S-NPP/Aqua varía en el espacio** (conteos 2012–2022, sin apagones):
  - por bloques de 2°: entre **3.75 y 12**;
  - por franjas de longitud en temporada alta: oeste (< −76°) 6.3, centro (−76° a −73°) 4.8, este (> −73°) 5.0;
  - en temporada baja: 9.7 / 7.2 / 9.8.

  Por eso el modelo C tiene sentido.
- **Fuente de datos geográficos: Microsoft Planetary Computer.** El equipo tiene acceso. El catálogo web es una app JS; para descubrir colecciones usa la API STAC `https://planetarycomputer.microsoft.com/api/stac/v1/collections/{id}`. El acceso es anónimo, con URL firmadas por el paquete `planetary-computer`. Colecciones verificadas (nov-2026):

  | id | contenido | uso |
  |---|---|---|
  | `nasadem` | NASADEM HGT v001, 30 m (SRTM 2000, **producto NASA**) | **recomendado** para costa/sierra/selva |
  | `cop-dem-glo-90` | Copernicus DEM, 90 m | alternativa de altitud |
  | `esa-cci-lc` | ESA CCI Land Cover, 300 m, anual 1992–2020 | zona por tipo de vegetación (explica la razón: el tamaño del fuego varía según la cobertura) |
  | `esa-worldcover` | ESA WorldCover 10 m, 2020–2021 | cobertura detallada |
  | `io-lulc-annual-v02` | LULC 9 clases, 10 m, 2017–2023 | no cubre 2012–2016 |
  | `modis-64A1-061` | MODIS Burned Area mensual (MCD64A1), 2000– | validación independiente de la serie armonizada, no sirve como zona |

  `modis-12Q1-061` (MODIS Land Cover) no respondió con ese id; falta averiguar el id correcto.
- **Plan propuesto, pendiente de confirmar por el usuario** (NASADEM o ESA CCI):
  1. Escribir un script que se corre una sola vez (`src/zones.py`): STAC → altitud mediana de cada celda de 0.25° de Perú (~1500 celdas). El resultado va a `config/zones_cells.csv` (pequeño y **versionado**, para que el equipo no tenga que volver a descargar).
  2. Clasificar: **sierra** ≥ 2000 m; **costa** < 2000 m al oeste de la cordillera; **selva** < 2000 m al este. El lado se define con la línea de altitud máxima en cada latitud. Ajustar los umbrales si quedan grupos muy desbalanceados.
  3. Modelo C en `calibration.py`: `y ~ C(week_id) + viirs:C(season):C(zona)`, sobre zona × semana a partir de `weekly_cell_sensor`. Se valida contra A y B con la misma regla de MAE > 5 %. Aunque no gane a nivel nacional, puede servir para Cusco.
  4. Dependencias solo para ese script: `pystac-client`, `planetary-computer` y `rasterio`. No están instaladas todavía y el pipeline principal no las necesita.
- Los datos VIIRS de 2025 y 2026 ya están descargados y versionados (commit `329ae03`). 2026 es NRT desde el 1-ago (ver "Datos NRT de 2026"). Las salidas de `output/` todavía se generaron con los datos hasta 2024. S-NPP terminó el 2-nov-2026 (verificado; su CSV llega al 1-nov).

## Equipo y convenciones de git
- Hay 5 personas, cada una dueña de un grupo de módulos (ver la sección 5 del README) para evitar conflictos de git. Mantén las firmas de las funciones stub, porque son los contratos entre integrantes.
- Commits en español con formato conventional: `tipo(ámbito): descripción en infinitivo`. Ejemplo: `feat(aggregate): implementar agregación semanal ISO con ceros explícitos`.
- No versionar `output/interim/`, `*.parquet` ni `*.csv.gz`. `output/reports/` **sí** se versiona. `dataset/` **sí** está versionado desde nov-2026 (la línea de `.gitignore` está comentada). Al volver a descargar el CSV de 2026, el NRT cambia y el diff es grande.
