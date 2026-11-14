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
