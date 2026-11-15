# Calendario de Actividad de Quema con NASA FIRMS (Perú - Caso de Estudio Cusco)

Proyecto para el desarrollo de un calendario y atlas de actividad de quema y riesgo de fuego en Perú (con foco en Cusco), armonizando observaciones satelitales históricas de NASA FIRMS (MODIS Aqua/Terra y VIIRS S-NPP/NOAA) mediante calibración empírica con Modelos Lineales Generalizados (GLM) para nutrir las salidas analíticas finales.

---

## 1. Estructura del Repositorio

```text
proyecto/
├── README.md                 # Este documento: guía y distribución de responsabilidades
├── requirements.txt          # Dependencias principales del proyecto
├── .gitignore                # Reglas de exclusión para datos pesados e intermedios
├── config/
│   └── settings.yaml         # Rutas, ventanas de calibración, umbrales y bounding box
├── dataset/                  # Archivos CSV crudos FIRMS por sensor (no van a git)
│   ├── modis/                # modis_{anio}_Peru.csv
│   ├── snpp/                 # viirs-snpp_{anio}_Peru.csv
│   ├── noaa20/               # viirs-jpss1_{anio}_Peru.csv (opcional)
│   └── noaa21/               # viirs-jpss2_{anio}_Peru.csv (opcional)
├── src/
│   ├── config.py             # Carga settings.yaml y resuelve rutas desde la raíz
│   ├── yaml_loader.py        # Cargador robusto para configuración YAML
│   ├── io_firms.py           # Búsqueda y carga de datos en memoria (find_files, load)
│   ├── cleaning.py           # Filtros puros: hora local (UTC-5), type, confianza, celdas
│   ├── audit.py              # Diagnóstico, razones entre sensores, alertas y gráficos
│   ├── aggregate.py          # Agregación diaria y semanal ISO (nacional y por celda) con ceros explícitos
│   ├── calibration.py        # GLM semanal Aqua→S-NPP: calibración, validación y factor final
│   ├── harmonize.py          # STUB: Aplicación del factor a la serie 2002-2011 agregada
│   ├── climatology.py        # STUB: Mediana histórica, percentiles y cálculo de anomalías
│   ├── export_web.py         # STUB: Exportación JSON/CSV de entrega final
│   ├── cli.py                # Interfaz CLI central del proyecto
│   └── legacy/               # Código monolítico original de referencia
│       └── firms_pipeline.py
├── output/
│   ├── reports/              # Reportes de auditoría de datos (CSV, PNG)
│   ├── interim/              # Tablas agregadas intermedias (daily_cell_sensor, weekly_sensor, weekly_cell_sensor)
│   └── processed/            # Series armonizadas finales y factores calibrados
└── docs/
    ├── decisiones.md         # Registro de decisiones metodológicas y científicas
    └── evidencia/            # Figuras y diagnósticos de auditoría y calibración
```

---

## 2. Instalación y Requisitos

El proyecto utiliza Python 3.10+ (probado en Python 3.15).

```bash
# 1. Crear y activar entorno virtual (opcional si ya cuentas con uno)
python -m venv venv
# En Windows:
.\venv\Scripts\activate
# En Linux/macOS:
source venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt
```

*Nota*: `pyarrow` es opcional; si no está disponible en la plataforma, el pipeline guarda automáticamente las tablas pesadas en formato `.csv.gz`.

---

## 3. Convención de Nombres de Archivos Crudos (`dataset/`)

Los archivos deben colocarse dentro de la carpeta `dataset/` respetando las siguientes subcarpetas y nombres:

| Fuente | Carpeta | Formato de Archivo | Descripción |
|---|---|---|---|
| MODIS | `dataset/modis/` | `modis_{YYYY}_Peru.csv` | Contiene observaciones de Terra y Aqua conjuntamente (diferenciados por la columna `satellite`). |
| VIIRS S-NPP | `dataset/snpp/` | `viirs-snpp_{YYYY}_Peru.csv` | Observaciones satelitales VIIRS Suomi-NPP (375 m). |
| VIIRS NOAA-20 | `dataset/noaa20/` | `viirs-jpss1_{YYYY}_Peru.csv` | *(Opcional)* Sensor VIIRS JPSS-1. |
| VIIRS NOAA-21 | `dataset/noaa21/` | `viirs-jpss2_{YYYY}_Peru.csv` | *(Opcional)* Sensor VIIRS JPSS-2. |

---

## 4. Cómo Ejecutar los Comandos

Todos los comandos se invocan desde la raíz del proyecto usando `src/cli.py`:

### A. Auditoría de Datos (`audit`)
Inspecciona la cobertura temporal, horas de paso orbital, proporciones de confianza, huecos de observación y razones entre sensores sin modificar los datos:
```bash
# Auditar el periodo por defecto definido en settings.yaml (2012-2017)
python src/cli.py audit

# Auditar años específicos
python src/cli.py audit --years 2012 2013 2014

# Auditar todos los años disponibles en dataset/
python src/cli.py audit --all-years
```
*Salidas generadas*: `output/reports/` (`audit_files.csv`, `audit_monthly.csv`, `audit_annual.csv`, `audit_ratios.csv`, `audit_annual_counts.png`, `audit_pass_time.png`).

### B. Construcción de Tabla Diaria (`build`)
Estandariza fechas a hora local peruana (UTC-5), elimina duplicados, categoriza confianza, calcula celdas espaciales de 0.25° y genera la tabla diaria agregada:
```bash
# Construir para el periodo por defecto (2012-2017)
python src/cli.py build

# Construir para un subconjunto de años
python src/cli.py build --years 2014 2015
```
*Salidas generadas*: `output/interim/` (`daily_cell_sensor`, `weekly_sensor` (semana × sensor), `weekly_cell_sensor` (semana × celda × sensor) en `.parquet` o `.csv.gz`, y `build_summary.csv`). Las tablas semanales usan semana ISO en hora local, incluyen ceros explícitos, `days_with_data` (días con observaciones del sensor) y la temporada definida en `settings.yaml`.

### C. Calibración GLM (`calibrate`)
Requiere haber ejecutado `build --all-years`. Ajusta los GLM semanales Aqua → S-NPP (modelo A: un factor; modelo B: factor por temporada) en la ventana de calibración, los valida en los años retenidos, elige el modelo y lo reajusta con todos los años estables (`windows` en `settings.yaml`):
```bash
python src/cli.py calibrate
```
*Salidas generadas*: `output/processed/` (`calibration_factors.csv`, `validation_metrics.csv`, `validation_monthly.csv`, `validation_noaa20_snpp.csv`, `harmonization_factors.csv` con el factor final y su IC 95 %, `calibration_summary.json`) y `output/reports/calibration_validation.png`.

### D. Personalización de Rutas
Es posible especificar carpetas personalizadas vía argumentos CLI:
```bash
python src/cli.py audit --modis-dir ruta/a/modis --snpp-dir ruta/a/snpp --out-dir ruta/salida
```

---

## 5. Distribución de Roles en el Equipo (Equipo de 5 personas)

Para evitar colisiones de Git durante el desarrollo del reto (~48 horas), cada integrante tiene asignada la propiedad de módulos específicos en `src/`:

| Integrante | Rol Principal | Módulos bajo su responsabilidad |
|---|---|---|
| **Persona 1** | Ingesta, Descarga y Limpieza | `dataset/`, `src/io_firms.py`, `src/cleaning.py`, `src/aggregate.py` |
| **Persona 2** | Modelado Estadístico y Calibración GLM | `src/calibration.py`, `src/harmonize.py`, `docs/decisiones.md` |
| **Persona 3** | Climatología, Percentiles y Anomalías | `src/climatology.py`, análisis espaciotemporal regional (Cusco) |
| **Persona 4** | Exportación de Productos de Datos | `src/export_web.py`, generación de JSON/CSV para el equipo de frontend externo |
| **Persona 5** | Documentación, Auditoría y Presentación | `docs/`, `output/reports/`, preparación de evidencias y entrega final |
