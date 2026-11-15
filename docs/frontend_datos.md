# Datos para el frontend (`output/web/`)

Contrato de los archivos que genera `python src/cli.py export` para la web del calendario y atlas de quemas. Versión del esquema: **1.0** (campo `version` en cada JSON).

> Si cambias un nombre de campo o su significado, sube `SCHEMA_VERSION` en [src/export_web.py](../src/export_web.py) y actualiza este documento en el mismo commit.

## 1. Cómo se generan

```powershell
$env:PYTHONIOENCODING="utf-8"
python src/cli.py harmonize      # serie única (si no existe)
python src/cli.py climatology    # línea base y anomalías (si no existe)
python src/cli.py export         # escribe output/web/ (unos 2.8 MB en 33 archivos)
```

`--out-dir <carpeta>` cambia el destino. La ruta por defecto está en `config/settings.yaml` → `paths.web`.

| Archivo | Vista | Tamaño aprox. | Cuándo cargarlo |
|---|---|---|---|
| `meta.json` | Leyenda, ámbitos, factores, índice | 3 KB | Siempre, al iniciar |
| `calendar_{ambito}.json` | Calendario año × mes | 110 KB | Vista calendario |
| `series_weekly_peru.json` | Serie semanal nacional | 630 KB | Vista serie temporal |
| `climatology_{ambito}.json` | Curva típica (mes y semana ISO) | 2–10 KB | Junto al calendario o la serie |
| `ranking_{ambito}.json` | Años ordenados | 4 KB | Vista ranking |
| `cells_index.json` | Celdas del mapa (id y centro) | 110 KB | Al abrir el mapa |
| `cells_{AAAA}.json` | Valores del mapa de un año | 50–100 KB | Al elegir el año (carga perezosa) |
| `regional_summary.csv` | Resumen ámbito × año | 4 KB | Descarga o tabla, opcional |

Los ámbitos (`{ambito}`) disponibles hoy son `peru` y `cusco`. No los escribas fijos en el código: léelos de `meta.json` → `ambitos`.

## 2. Reglas comunes a todos los archivos

1. **`null` significa "sin dato", nunca cero.** Un `0` es un cero real de detecciones. Un `null` es que no hubo observación válida o que el campo no aplica. Dibuja los `null` como un hueco (la línea se corta y la casilla queda gris), nunca como 0.
2. **Unidades.**
   - `count`: número de focos de calor en **equivalente VIIRS 375 m**. En 2002–2011 es un valor estimado (Aqua × factor), así que puede ser fraccionario en el origen; se exporta redondeado a entero.
   - `frp`: suma de la potencia radiativa del fuego, en **MW**.
3. **Redondeo.** Conteos y FRP son enteros. Porcentajes y percentiles llevan 1 decimal. Los factores llevan 3 decimales.
4. **Fechas.** Los meses se describen con `anio` + `mes` (1–12). Las semanas se describen con `semana`, en formato `"AAAA-MM-DD"`: es el **lunes** de la semana ISO, en hora local de Perú (UTC−5).
5. **Ids sin acentos.** Las categorías, los tramos y las temporadas se identifican con ids ASCII. El texto que ve el usuario (con acentos) y los colores están en `meta.json`.
6. **JSON compacto, en UTF-8, sin `NaN`.** Se puede leer con `fetch(...).then(r => r.json())`.
7. **Tramo.** Cada valor dice de dónde viene:
   - `estimado` (2002–2011): MODIS Aqua × factor de calibración. Hay que **marcarlo visualmente** (trama, línea discontinua o etiqueta "estimado").
   - `viirs_real` (2012 en adelante): detecciones reales de VIIRS.

## 3. `meta.json`

Se carga primero. Sirve para construir la leyenda, los selectores y los textos de "acerca de".

```json
{
  "version": "1.0",
  "generado": "2026-11-15",
  "linea_base": [2003, 2024],
  "ambitos": {
    "peru":  {"nombre": "Perú",  "bbox": null, "provisional": false, "tiene_bandas": true,  "tiene_semanal": true},
    "cusco": {"nombre": "Cusco", "bbox": [-15.8, -11.2, -74.0, -70.3], "provisional": true, "tiene_bandas": false, "tiene_semanal": false}
  },
  "categorias": [
    {"id": "muy_por_debajo", "etiqueta": "Muy por debajo",    "color": "#5e3c99", "orden": 0},
    {"id": "por_debajo",     "etiqueta": "Por debajo",        "color": "#b2abd2", "orden": 1},
    {"id": "normal",         "etiqueta": "Normal",            "color": "#f7f7f7", "orden": 2},
    {"id": "por_encima",     "etiqueta": "Por encima",        "color": "#fdb863", "orden": 3},
    {"id": "muy_por_encima", "etiqueta": "Muy por encima",    "color": "#e66101", "orden": 4},
    {"id": "maximo",         "etiqueta": "Máximo histórico",  "color": "#7f2704", "orden": 5},
    {"id": "sin_dato",       "etiqueta": "Sin dato completo", "color": "#bdbdbd", "orden": 6}
  ],
  "tramos": [
    {"id": "estimado",   "etiqueta": "Estimado (MODIS Aqua × factor)", "anios": [2002, 2011]},
    {"id": "viirs_real", "etiqueta": "VIIRS real",                     "anios": [2012, null]}
  ],
  "fuentes":   {"estimado": "...", "S-NPP": "...", "NOAA-20": "...", "NOAA-21": "...", "sin dato": "..."},
  "calidades": {"ok": "...", "parcial": "...", "incompleto": "...", "relleno": "...", "sin dato": "..."},
  "temporadas": {"alta": [8, 9], "media": [6, 7, 10, 11], "baja": [12, 1, 2, 3, 4, 5]},
  "unidades":  {"count": "focos de calor (equivalente VIIRS 375 m)", "frp": "MW (suma de FRP)"},
  "modelo": "B",
  "factores": {
    "count": {"alta": {"factor": 4.973, "ic_inf": 4.703, "ic_sup": 5.258}, "media": {}, "baja": {}},
    "frp":   {"alta": {"factor": 1.781, "ic_inf": 1.691, "ic_sup": 1.876}, "media": {}, "baja": {}}
  },
  "cobertura_banda": 0.9,
  "semana_inicio": "2002-07-01",
  "semana_fin": "2024-12-23",
  "celdas_anios": [2002, 2003, 2004],
  "archivos": {"calendar_peru.json": {"vista": "calendar", "ambito": "peru"}}
}
```

| Campo | Significado |
|---|---|
| `ambitos.{id}.bbox` | Rectángulo `[lat_min, lat_max, lon_min, lon_max]` del área; `null` para todo Perú. Sirve para dibujar el recuadro en el mapa. |
| `ambitos.{id}.provisional` | `true` si el recorte del área todavía no es definitivo (Cusco). Muestra un aviso. |
| `ambitos.{id}.tiene_bandas` | Si las series de ese ámbito traen `count_inf`/`count_sup`. Cusco no las tiene. |
| `ambitos.{id}.tiene_semanal` | Si existe la serie y la climatología semanal. Hoy solo Perú. |
| `categorias` | Semáforo de anomalías, en orden de menor a mayor. `color` usa la paleta PuOr (apta para daltonismo); úsala tal cual para que coincida con los PNG de `output/reports/`. |
| `factores` | Factor VIIRS/Aqua por temporada con su IC 95 %. Sirve para el texto metodológico. |
| `cobertura_banda` | Cobertura nominal de la banda `*_inf`/`*_sup` (0.9 = banda de predicción del 90 %). |
| `celdas_anios` | Años con un archivo `cells_{AAAA}.json`. |
| `archivos` | Índice de los archivos generados. `cells_{anio}.json` es una plantilla. |

## 4. `calendar_{ambito}.json`: calendario año × mes

Es la vista principal: una matriz de años (filas) por meses (columnas), con cada casilla coloreada según `cat`.

```json
{
  "version": "1.0",
  "ambito": "peru",
  "linea_base": [2003, 2024],
  "anios": [2002, 2024],
  "tiene_bandas": true,
  "meses": [
    {"anio": 2003, "mes": 9, "temporada": "alta", "tramo": "estimado", "fuente": "estimado", "calidad": "ok",
     "dias_mes": 30, "dias_estimado": 30, "dias_sin_dato": 0,
     "count": 22397, "count_inf": 19800, "count_sup": 25900,
     "frp": 210000, "frp_inf": 180000, "frp_sup": 230000,
     "mediana": 21000, "p10": 12000, "p25": 15000, "p75": 26000, "p90": 31000, "maximo": 40000,
     "anomalia": 1397, "anomalia_pct": 6.7, "percentil": 57.1,
     "cat": "normal", "cat_inf": "normal", "cat_sup": "por_encima", "incierta": true}
  ]
}
```
*(Los valores del ejemplo son ilustrativos.)*

Hay una fila por mes, desde 2002-07 hasta 2024-12 (270 meses), en orden cronológico. Los meses anteriores a julio de 2002 **no existen** en la lista: dibújalos como casillas vacías.

| Campo | Tipo | Significado |
|---|---|---|
| `anio`, `mes` | int | Año y mes (1–12). |
| `temporada` | `alta` \| `media` \| `baja` | Temporada de quema del mes. |
| `tramo` | `estimado` \| `viirs_real` | Ver la regla 7. |
| `fuente` | string | Sensor del valor: `estimado`, `S-NPP`, `NOAA-20+S-NPP`, `S-NPP+estimado`, etc. Un `+` indica que el mes mezcla semanas de varias fuentes. |
| `calidad` | `ok` \| `incompleto` \| `parcial` \| `relleno` | `incompleto`: el mes tiene días sin dato (2002-07, 2002-08 y 2010-02). |
| `dias_mes`, `dias_estimado`, `dias_sin_dato` | int | Días del mes, días con valor estimado y días sin dato. |
| `count`, `frp` | int | Valor del mes. |
| `count_inf`, `count_sup`, `frp_inf`, `frp_sup` | int \| null | Banda de predicción mensual del 90 %. En `viirs_real` es igual al valor, porque es un dato observado. En Cusco es `null` (no hay bandas para áreas). |
| `mediana`, `p10`, `p25`, `p75`, `p90`, `maximo` | int | Climatología del **mismo mes** en la línea base. Con estos campos se dibuja la "caja normal" en el tooltip. |
| `anomalia`, `anomalia_pct` | int, float \| null | `count − mediana` y la misma diferencia en % de la mediana. `null` si `cat = sin_dato`. |
| `percentil` | float \| null | Percentil empírico (0–100) del valor dentro de la línea base. `null` si `cat = sin_dato`. |
| `cat` | id de categoría | Color de la casilla. |
| `cat_inf`, `cat_sup` | id \| null | Categoría que tendría el mes con la banda inferior y con la superior. Solo existe donde hay bandas. |
| `incierta` | bool \| null | `true` si `cat_inf ≠ cat_sup`, es decir, si la incertidumbre del factor puede cambiar el color. |

**Cómo dibujarlo:**
- Rellena cada casilla con el color de `cat`, buscado en `meta.categorias`.
- Si `tramo = estimado`, agrega una trama o un borde punteado. Si además `incierta = true`, agrega un indicador como "≈" o un punto en la esquina.
- En el tooltip muestra `count` (con `count_inf`–`count_sup` si no son `null`), `anomalia_pct`, `percentil`, la `fuente` y la `calidad`.

## 5. `series_weekly_peru.json`: serie semanal nacional

```json
{
  "version": "1.0",
  "ambito": "peru",
  "linea_base": [2003, 2024],
  "semana_inicio": "2002-07-01",
  "semana_fin": "2024-12-23",
  "cobertura_banda": 0.9,
  "semanas": [
    {"semana": "2013-12-30", "anio": 2014, "semana_iso": 1, "mes": 1, "temporada": "baja",
     "tramo": "viirs_real", "fuente": "S-NPP", "calidad": "ok", "dias_viirs": 7,
     "count": 589, "count_inf": 589, "count_sup": 589, "count_ic_inf": 589, "count_ic_sup": 589,
     "frp": 4907, "frp_inf": 4907, "frp_sup": 4907, "frp_ic_inf": 4907, "frp_ic_sup": 4907,
     "aqua_count": 111, "factor_count": 8.944,
     "mediana": 273, "p10": 146, "p25": 188, "p75": 567, "p90": 808, "maximo": 1386,
     "anomalia": 316, "anomalia_pct": 116.0, "percentil": 75.0,
     "cat": "por_encima", "cat_inf": "por_encima", "cat_sup": "por_encima", "incierta": false}
  ]
}
```

Hay 1174 semanas consecutivas, sin saltos. Las semanas sin observación siguen en la lista con `count = null`.

| Campo | Significado |
|---|---|
| `semana` | Lunes de la semana ISO (`AAAA-MM-DD`). Úsalo como eje X. |
| `anio`, `semana_iso` | Año ISO y número de semana (1–53). **Ojo:** el año ISO puede no coincidir con el año del lunes. En el ejemplo, la semana que empieza el 2013-12-30 es la semana 1 de 2014. |
| `mes` | Mes del jueves de la semana. Es el que define la `temporada`. |
| `fuente` | `estimado`, `S-NPP`, `NOAA-20` o `sin dato`. NOAA-20 reemplaza a S-NPP en las semanas en que S-NPP falló. |
| `calidad` | `ok`, `parcial` (la primera semana, 2002-07-01), `relleno` (4 semanas de 2012 sin VIIRS válido, que se rellenaron con Aqua × factor) o `sin dato`. |
| `dias_viirs` | Días de la semana con datos VIIRS (`null` en el tramo estimado). |
| `count`, `frp` | Valor de la semana. `null` en las 3 semanas sin dato: 2002-07-29, 2002-08-05 y 2010-02-01. |
| `count_inf`, `count_sup` | **Banda de predicción semanal del 90 %.** Es la incertidumbre real de una semana estimada. Es **asimétrica** y más ancha en temporada baja: en mediana va de −24 %/+36 % en temporada alta a −42 %/+235 % en temporada baja. **Es la banda que conviene mostrar.** |
| `count_ic_inf`, `count_ic_sup` | IC 95 % del factor (±6 %). Es mucho más estrecho: **no lo uses como banda de la serie**, porque solo describe la incertidumbre del factor promedio. |
| `aqua_count`, `factor_count` | Focos de Aqua y el factor aplicado. Sirven para un tooltip del tipo "estimado = 111 × 8.94". |
| `mediana` … `incierta` | Igual que en el calendario, pero contra la climatología de la **semana ISO** (la semana 53 se compara con la 52). |

**Cómo dibujarlo:**
- Línea de `count` y área sombreada entre `count_inf` y `count_sup`.
- En `viirs_real` la banda coincide con la línea, así que la sombra desaparece sola.
- Corta la línea en los `null`. Con D3, usa `line.defined(d => d.count !== null)`; con Chart.js, `spanGaps: false`.
- Puedes agregar de fondo la franja p25–p75 de la climatología.

## 6. `climatology_{ambito}.json`: curva típica

```json
{
  "version": "1.0",
  "ambito": "peru",
  "linea_base": [2003, 2024],
  "mensual": [
    {"mes": 1, "n_anios": 22, "media": 1999, "mediana": 1607, "p10": 882, "p25": 1070, "p75": 2671, "p90": 3435,
     "minimo": 733, "maximo": 4588, "anio_minimo": 2009, "anio_maximo": 2004}
  ],
  "semanal": [
    {"semana_iso": 1, "n_anios": 22, "media": 432, "mediana": 273, "p10": 146, "p25": 188, "p75": 567, "p90": 808,
     "minimo": 98, "maximo": 1386, "anio_minimo": 2007, "anio_maximo": 2003}
  ]
}
```

- `mensual` tiene 12 filas.
- `semanal` tiene 52 filas, o es `null` si el ámbito no tiene serie semanal (Cusco).
- `n_anios` es el número de años completos de la línea base que entraron en el cálculo. Puede ser menor a 22 si algún año tuvo ese mes incompleto.
- La climatología solo trae **conteos**, no FRP.

Uso típico: un gráfico de "año seleccionado vs. normal". Dibuja la franja p10–p90 y, encima, la p25–p75, la línea de la mediana y por último la línea del año elegido, tomada del calendario o de la serie semanal.

## 7. `ranking_{ambito}.json`: años ordenados

```json
{
  "version": "1.0",
  "ambito": "cusco",
  "linea_base": [2003, 2024],
  "anios": [
    {"anio": 2020, "tramo": "viirs_real", "completo": true, "puesto": 1, "percentil": 95.2,
     "count": 11515, "frp": 130947, "anomalia_pct": 111.8, "mes_pico": 8, "count_mes_pico": 4304, "pct_ago_sep": 54.7}
  ]
}
```

- La lista viene ordenada por `puesto`, de 1 al último. Los años sin puesto (`completo = false`, como 2002, que empieza en julio) van al final.
- `anomalia_pct` es la diferencia del total anual frente a la mediana de los totales anuales de la línea base.
- `pct_ago_sep` es el porcentaje del año que cae en agosto–septiembre.
- `mes_pico` es el mes (1–12) con más focos.

## 8. Mapa: `cells_index.json` + `cells_{AAAA}.json`

La malla es de **celdas de 0.25°**, unos 28 km. Hay dos archivos para no repetir la geometría en cada año.

**`cells_index.json`** (se carga una vez):
```json
{
  "version": "1.0",
  "tamano_celda": 0.25,
  "celdas": [
    {"id": "-13.375_-71.875", "lat": -13.375, "lon": -71.875, "ambitos": ["cusco"]}
  ]
}
```
- `lat` y `lon` son el **centro** de la celda. El cuadrado se dibuja desde `lat ± 0.125` y `lon ± 0.125`.
- `ambitos` lista las áreas (fuera de Perú) que contienen el centro de la celda. Sirve para resaltar las celdas de Cusco o para hacer zoom.
- Hay 1680 celdas: todas las que tuvieron algún foco en algún año.

Polígono GeoJSON de una celda:
```js
const h = idx.tamano_celda / 2;
const ring = [[c.lon-h,c.lat-h],[c.lon+h,c.lat-h],[c.lon+h,c.lat+h],[c.lon-h,c.lat+h],[c.lon-h,c.lat-h]];
```

**`cells_{AAAA}.json`** (uno por año):
```json
{
  "version": "1.0",
  "anio": 2002,
  "tramo": "estimado",
  "meses_con_dato": [false, false, false, false, false, false, true, true, true, true, true, true],
  "calidad_meses":  [null, null, null, null, null, null, "incompleto", "incompleto", "ok", "ok", "ok", "ok"],
  "max_count": 925,
  "celdas": {
    "-1.125_-74.375": {"count": 5, "frp": 14, "meses": [null, null, null, null, null, null, 0, 0, 5, 0, 0, 0]}
  }
}
```

| Campo | Significado |
|---|---|
| `meses_con_dato[i]` | `false` si el mes `i+1` no tiene datos en todo el país (ene–jun de 2002). |
| `calidad_meses[i]` | Calidad nacional de cada mes. Es la misma que en `calendar_peru.json`. |
| `max_count` | Valor anual máximo entre las celdas. Sirve para escalar la paleta de un año. Para comparar años, usa una escala fija. |
| `celdas` | **Solo incluye las celdas con focos > 0 en el año.** Una celda del índice que no aparece aquí vale 0, no `null`. |
| `celdas.{id}.meses` | 12 valores mensuales. `null` cuando `meses_con_dato` es `false`. |

**Limitaciones del mapa (importante para los textos):**
- **No hay semáforo ni anomalías por celda.** El percentil de una celda de 28 km es muy ruidoso. Muestra valores absolutos (focos o FRP) con una escala secuencial, no la paleta del semáforo.
- **No hay bandas por celda.** Los valores de 2002–2011 son estimados (Aqua × factor nacional) y se ven más "granulados" que los de VIIRS: muchas celdas en 0 y otras con saltos de ~5–9 focos, porque un solo foco de Aqua equivale a esa cantidad. Conviene avisarlo en la leyenda cuando `tramo = estimado`.
- En los meses de lluvia (ene–abr) de 2002–2011, las celdas pequeñas suelen valer 0 por la menor sensibilidad de Aqua. No es ausencia real de fuego.
- La suma de las celdas coincide con el total nacional del calendario con una diferencia menor al 0.2 %, que viene del redondeo a enteros por celda.

## 9. `regional_summary.csv`

Es un resumen ámbito × año para descargar o mostrar en una tabla simple. Columnas:

`ambito, anio, tramo, n_meses, count, frp, mes_max, count_mes_max, cat_mes_max, meses_sobre_normal, meses_bajo_normal, meses_sin_dato, meses_inciertos`

- `meses_sobre_normal` cuenta los meses en `por_encima`, `muy_por_encima` o `maximo`.
- `meses_bajo_normal` cuenta los meses en `por_debajo` o `muy_por_debajo`.

## 10. Mensajes y advertencias que el front debe mostrar

| Situación | Cómo detectarla | Texto sugerido |
|---|---|---|
| Valor estimado | `tramo == "estimado"` | "Estimado a partir de MODIS Aqua (2002–2011), calibrado con VIIRS." |
| Color incierto | `incierta == true` | "Dentro del margen de error podría ser «{cat_inf}» o «{cat_sup}»." |
| Sin dato | `count == null` o `cat == "sin_dato"` | "Sin observación completa del satélite en este período." |
| Área provisional | `meta.ambitos[a].provisional` | "Recorte rectangular aproximado; incluye bordes de regiones vecinas." |
| FRP estimado | `tramo == "estimado"` en una vista de FRP | "El FRP estimado tiende a sobrestimarse (~+12 % en validación)." |
| Cusco sin bandas | `!meta.ambitos[a].tiene_bandas` | No dibujes la banda; agrega una nota: "la incertidumbre del estimado no está calculada para áreas". |

## 11. Ejemplo mínimo de carga

```js
const base = "data/";                       // carpeta donde se copia output/web/
const get = (f) => fetch(base + f).then((r) => r.json());

const meta = await get("meta.json");
const color = Object.fromEntries(meta.categorias.map((c) => [c.id, c.color]));

const cal = await get("calendar_peru.json");
for (const m of cal.meses) {
  const cell = document.querySelector(`[data-a="${m.anio}"][data-m="${m.mes}"]`);
  cell.style.background = color[m.cat];
  cell.classList.toggle("estimado", m.tramo === "estimado");
  cell.classList.toggle("incierta", m.incierta === true);
  cell.title = m.count === null ? "Sin dato"
    : `${m.count.toLocaleString("es-PE")} focos (${m.anomalia_pct ?? "–"} % vs. mediana)`;
}

// Mapa: el índice se carga una vez y cada año bajo demanda
const idx = await get("cells_index.json");
const year = await get(`cells_${meta.celdas_anios.at(-1)}.json`);
const value = (id) => year.celdas[id]?.count ?? 0;   // la celda ausente vale 0, no null
```

## 12. Cosas que todavía no están (y podrían cambiar el esquema)

- **Serie semanal y climatología semanal de Cusco.** Hoy `climatology` solo calcula la semanal para Perú. Cuando exista, aparecerá `series_weekly_cusco.json` y `tiene_semanal` pasará a `true`.
- **Recorte definitivo de Cusco.** El rectángulo cambiará por un polígono administrativo; `bbox` podría pasar a ser un GeoJSON.
- **Modelo C (factor por zona costa/sierra/selva).** Cambiaría los valores de 2002–2011 por celda y en Cusco, pero no los nombres de los campos.
- **Datos de 2025 y continuidad con NOAA-20/21.** S-NPP dejó de entregar datos en noviembre de 2026. Las semanas nuevas vendrán de NOAA-20 (`fuente = "NOAA-20"`); el esquema no cambia.
