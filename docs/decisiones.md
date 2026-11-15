# Registro de Decisiones Metodológicas y Técnicas

Este documento reúne las decisiones clave adoptadas para el diseño del pipeline y la armonización de puntos calientes NASA FIRMS (Perú, caso de estudio Cusco).

---

## 1. Aqua como Referencia Principal de MODIS
- **Decisión**: Se selecciona MODIS Aqua como el sensor de referencia para la familia MODIS en la calibración empírica con VIIRS.
- **Fundamento**: La órbita de Aqua tiene una hora de paso diurna local ecuatorial alrededor de las 13:30 h, que coincide estrechamente con el paso de los satélites VIIRS (S-NPP alrededor de las 13:30 h). Esto minimiza diferencias atribuibles al ciclo diurno de quema y combustión de biomasa.

## 2. Exclusión de Terra de la Calibración
- **Decisión**: Los datos del sensor Terra se mantienen separados y se excluyen de la calibración empírica principal con VIIRS (utilizándose exclusivamente como análisis de sensibilidad).
- **Fundamento**: Durante el periodo de solapamiento (2012–2017), Terra detecta en promedio únicamente ~20 % del conteo registrado por Aqua (razón Terra/Aqua ≈ 0.20). Esta marcada diferencia responde a su hora de paso matutina local (~10:30 h), momento del día en que la actividad de quema agrícola y forestal en los Andes y la Amazonía aún no alcanza su pico térmico diurno, y no a una deriva orbital instrumental.

## 3. VIIRS como una Serie Temporal Unificada
- **Decisión**: Tratar los datos de VIIRS S-NPP (y a futuro NOAA-20 / NOAA-21) como una serie observacional de alta resolución unificada.
- **Fundamento**: Los instrumentos VIIRS comparten idéntica resolución espacial de 375 m en bandas I (frente a 1 km en MODIS) y algoritmos de detección análogos. Durante la fase de solapamiento 2012–2017, S-NPP constituye el sensor representativo continuo de la era moderna.

## 4. Calibración Semanal por Modelo Lineal Generalizado (GLM)
- **Decisión**: La relación empírica entre MODIS y VIIRS se ajusta a escala semanal agregada (semana ISO × celda geográfica) mediante un GLM (familia cuasi-Poisson o Binomial Negativa).
- **Fundamento**: La agregación semanal mitiga el ruido introducido por nubosidad efímera interdiaria y asegura tamaños de muestra con varianza controlada en celdas de 0.25°. El GLM permite modelar datos de conteo con sobredispersión sin asumir relaciones lineales gaussianas incorrectas.

## 5. Validación con Años Retenidos (Hold-Out)
- **Decisión**: El modelo se entrena en la ventana de solapamiento 2012–2017 y se valida rigurosamente en una ventana posterior retenida (2018–2022).
- **Fundamento**: Garantiza que el factor o función predictiva generalice adecuadamente en años no vistos con diferentes intensidades climáticas (como eventos El Niño o anomalías extremas de precipitación) antes de aplicarlo hacia atrás.

## 6. Aplicación de Factores Únicamente a Nivel Agregado
- **Decisión**: El factor de armonización y las relaciones del GLM se aplican estrictamente a series agregadas temporales y espaciales (conteos y FRP total por celda/semana).
- **Fundamento**: **Los puntos calientes crudos individuales no se armonizan ni se sintetizan**. Transformar detecciones geográficas individuales induciría falsos positivos y errores posicionales espurios dado el contraste de resolución entre la huella de 1 km de MODIS y 375 m de VIIRS.

## 7. Agregación Semanal ISO con Ceros Explícitos y Cobertura
- **Decisión**: La tabla semanal (`weekly_sensor`, `weekly_cell_sensor`) usa semana ISO en hora local, incluye ceros explícitos y la columna `days_with_data` (días de la semana con al menos una detección del sensor en el dominio).
- **Fundamento**: Omitir las semanas sin detecciones sesga el GLM hacia arriba. `days_with_data` distingue "cero fuegos" de "satélite sin observaciones".

## 8. Temporadas de Quema Definidas con los Datos
- **Decisión**: alta = ago–sep, media = jun–jul y oct–nov, baja = dic–may (mes del jueves de la semana ISO; configurable en `settings.yaml`).
- **Fundamento**: En 2002–2024, ago–sep concentran ~60–65 % de las detecciones y jul–oct ~85 %, con perfiles casi idénticos en Aqua, S-NPP y NOAA-20.

## 9. Filtro de Semanas para la Calibración
- **Decisión**: Se excluyen (a) las semanas que se solapan con un apagón documentado por NASA (`settings.yaml` → `outages`, columna `in_outage`), (b) las semanas en que Aqua no tiene observaciones (`days_with_data == 0`) y (c) las semanas en que VIIRS tiene menos de 6 días con datos (`MIN_TARGET_DAYS`).
- **Apagones documentados**:
  - **Aqua, del 16 de agosto al 2 de septiembre de 2020.** Falló la unidad FMU del satélite y solo hubo cobertura parcial por *Direct Broadcast* (MODIS C6 Active Fire User's Guide, rev. C, sec. 7.2.4). Esto explica el desajuste de agosto de 2020: Aqua detectaba decenas de focos por día mientras S-NPP detectaba miles. Al excluir esas semanas, la correlación de 2020 sube de 0.74 a 0.97.
  - **S-NPP, del 27 de julio al 10 de agosto de 2022** (VIIRS C2 Burned Area User's Guide v1.1, sec. 8.2).
- **Fundamento**: VIIRS detecta algún fuego en Perú casi todos los días, así que una semana incompleta es un apagón. A Aqua no se le exigen más días porque, en temporada baja, tener pocos días con detecciones refleja ausencia de fuego. Para apagones no documentados se mantienen los filtros por `days_with_data`.

## 10. GLM con Efecto Fijo de Semana y Errores Agrupados
- **Decisión**: `y ~ C(week_id) + viirs` (A) y `y ~ C(week_id) + viirs:C(season)` (B) sobre la tabla semanal nacional. Conteos con Poisson y FRP total con Tweedie (p = 1.5, enlace log). Errores estándar agrupados por semana. El factor es exp(β) con IC 95 %.
- **Fundamento**: El efecto fijo de semana absorbe la actividad real de fuego. La dispersión de Pearson (~9–14 en conteos) confirma la sobredispersión, pero los errores agrupados la incorporan en la inferencia sin cambiar la estimación puntual, así que no hace falta pasar a binomial negativa. Se usa Tweedie y no Gamma porque hay semanas con FRP = 0.

## 11. Selección del Modelo y Reajuste Final
- **Decisión**: Se elige el modelo más simple salvo que uno más complejo reduzca el MAE semanal de validación (2018–2022) en más de 5 %. El modelo elegido se reajusta con 2012–2022 (`windows.final`).
- **Fundamento**: Tras excluir los apagones, en validación el modelo B reduce el MAE semanal de conteos de 316 a 262 (−17 %); el error total es +2.7 % y la correlación 0.98. La razón VIIRS/Aqua es mayor en temporada baja (~8.8) que en alta (~5.0), porque en temporada baja hay más focos pequeños que MODIS (1 km) no detecta. La ventana final termina en 2022 porque Aqua deriva de su órbita desde 2023 (hora de paso mediana de 13:51 en 2023 y 14:16 en 2024, frente a ~13:35 antes).
- **Advertencias**:
  - La banda IC 95 % refleja la incertidumbre del factor, no el error semanal: cubre ~18 % de las semanas observadas.
  - El factor de FRP sobreestima en validación (+11 % en total), así que hay que presentarlo con cautela.

## 12. Inconsistencia de `type` entre Versiones de MODIS (corregida con máscara de fuentes estáticas)
- **Hallazgo**: Los CSV de FIRMS mezclan versiones de MODIS: `6.2` en 2002–2017, `6.03` en 2018–2022 y `61.03` (Colección 6.1) en 2023–2024. Desde la versión 03, el tipado de fuentes estáticas mejoró (MODIS C6 Fire User's Guide rev. C, sec. 5.5.2 y 7.2.3). Aqua marca `type=2/1` en ~1.8–2.3 % de sus focos desde 2018, pero en <0.5 % antes. VIIRS (versión 2) es consistente en todos los años (~2–3 %).
- **Impacto**: Antes de 2018, ~1–1.5 % de las detecciones de Aqua con `type=0` están en ubicaciones que después se clasifican como estáticas: industria, volcanes, zonas urbanas. Esto infla levemente a Aqua en la calibración (2012–2017) frente a la validación (2018–2022), sesgando el factor ~1–2 % a la baja. Además deja puntos "eternos" en la climatología 2002–2011.
- **Solución implementada**: Máscara de ubicaciones estáticas (`cleaning.build_static_mask`, `static_mask_keys`, `flag_static`; se arma en `aggregate.build_mask` durante `build`).
  - Se juntan todas las detecciones `type ∈ {1, 2}` de **cualquier sensor y año**, siempre con todos los archivos disponibles, aunque se use `--years`. Así la máscara no depende de los años procesados.
  - Se agrupan en celdas de **0.01°** (~1.1 km, del tamaño del píxel MODIS). Una celda es estática si tuvo `type` 1/2 en **al menos 2 años distintos** (persistencia, como la definición de FIRMS). Se añade un margen de **±1 celda** por el error de geolocalización de MODIS.
  - Se excluyen de la tabla diaria (y por tanto de las semanales) los focos `type=0` que caen en esas celdas, en todos los años. Parámetros en `settings.yaml` → `static_mask`. La máscara se guarda en `output/interim/static_mask` y lo eliminado por archivo en `build_summary.csv` (`static_loc_removed`).
  - `audit` no aplica la máscara: audita el dato crudo.
- **Cómo se eligió**: Se probaron celdas de 0.005–0.02°, con y sin margen y con persistencia de 1 o 2 años. Sin persistencia y con margen se eliminaba 5–6 % de VIIRS, en su mayoría incendios reales cerca de fuentes estáticas. La opción elegida (364 celdas, 2041 con margen) elimina poco y deja dentro las fuentes grandes: el volcán Sabancaya, la fundición de Ilo, la planta de gas de Malvinas (Camisea), la zona de Pampa Melchorita/Pisco, Chimbote y Talara.
- **Resultado** (focos `type=0` eliminados por la máscara):

  | período | Aqua | Terra | S-NPP | NOAA-20 |
  |---|---|---|---|---|
  | 2002–2011 | 1.26 % | 5.18 % | — | — |
  | 2012–2017 | 1.49 % | 7.29 % | 1.56 % | — |
  | 2018–2022 | 0.81 % | 2.76 % | 1.52 % | 1.46 % |

  Aqua pierde casi el doble antes de 2018 que después, lo que confirma el tipado deficiente de la versión 6.2. S-NPP pierde lo mismo en todos los años.
- **Efecto en la calibración: menor de lo previsto.** La razón S-NPP/Aqua de 2012–2017 casi no cambia (5.762 → 5.759), porque la máscara también quita ~1.5 % de S-NPP en esos años. Factores finales: alta 4.98 → 4.97, media 6.69 → 6.66, baja 8.84 → 8.94 (+1.1 %; en la temporada baja las fuentes estáticas pesan más). La validación queda prácticamente igual (modelo B: error total +2.7 % → +3.8 %, MAE relativo 19.8 % → 20.0 %, corr 0.98). El mayor beneficio está en la serie 2002–2011 y en la climatología, que ya no tienen puntos industriales "eternos".
