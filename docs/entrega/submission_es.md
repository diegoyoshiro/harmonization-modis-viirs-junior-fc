# Entrega Space Apps 2026: versión en español (para el equipo)

> **Este archivo es solo para que el equipo entienda y discuta el contenido. NO se pega en la web de Space Apps.** Lo que se envía es [submission_en.md](submission_en.md), en inglés. Las secciones de ambos archivos se corresponden una a una: si cambian una, cambien la otra.
> - `[[ ]]` = dato pendiente. ⟳ = cifra que se actualiza si se vuelve a correr el pipeline.
> - Cierre: **domingo 15-nov-2026, 23:59 hora del evento local**.
>
> **Niveles de lectura** (de lo más simple a lo más técnico):
> 1. **Slides / video** → cualquier persona. Una idea por slide y sin jerga.
> 2. **Resumen** → un párrafo sin jerga.
> 3. **Descripción detallada** → empieza en lenguaje simple y termina con el detalle técnico. Ese detalle es lo que puntúa en **Validity** (base científica).

---

## 1. Nombre del proyecto

**FireCal Perú: un registro de fuego, dos satélites de NASA, 22 años**

Alternativas:
- *Calendario de Quemas Perú: ¿esta temporada de fuego es normal?*
- *Dos satélites, un solo registro de fuego*

---

## 2. Resumen general

Los satélites de NASA observan los incendios en Perú desde hace más de 20 años, pero con dos instrumentos distintos. El más nuevo (VIIRS, desde 2012) es mucho más nítido y ve entre 5 y 9 veces más focos que el antiguo (MODIS, desde 2002). Si se juntan ambos registros, parece que los incendios explotaron en 2012, pero ese salto es solo el instrumento nuevo. Lo corregimos. En los años en que ambos satélites volaron juntos, aprendimos el "tipo de cambio" entre ellos, temporada por temporada. Lo probamos en años que nunca había visto y luego lo usamos para convertir el registro antiguo a la escala del nuevo. El resultado es una sola historia de fuego comparable para Perú, de 2002 a hoy, con márgenes de error honestos. Sobre ella construimos un calendario de quemas y un "semáforo". Así, brigadas, autoridades locales e investigadores, empezando por Cusco, pueden saber si la actividad de fuego de este mes es normal o alarmante.

---

## 3. Enlace al demo

`[[enlace público a las slides o al video ≤ 30 s]]`

---

## 4. Enlace al proyecto final

`[[sitio web]]`, `https://github.com/diegoyoshiro/harmonization-modis-viirs-junior-fc` (debe ser público).

---

## 5. Descripción detallada

### En palabras simples
Imagina comparar fotos de hoy, tomadas con un celular, con fotos antiguas de una cámara barata: hoy ves más detalle, pero eso no significa que haya más cosas. Con los satélites de fuego pasa lo mismo. Construimos un "traductor" entre el sensor antiguo y el nuevo de NASA, para que Perú tenga por fin una sola historia de fuego comparable año a año desde 2002.

### ¿Qué hace?
- **Una historia de fuego armonizada** para Perú (2002–2024), por semana, mes y año, también en una grilla de mapa. Cada valor dice si es *estimado* (2002–2011, traducido del sensor antiguo) u *observado* (desde 2012) y trae su margen de error.
- **Un calendario de quemas** (año × mes) que muestra cuándo empieza la temporada, cuándo llega al pico (agosto–septiembre) y cuándo termina.
- **Un "semáforo" de anomalías**: cada mes se compara con lo normal de 2003–2024 y se clasifica desde "muy por debajo de lo normal" hasta "extremo". Los colores son aptos para daltonismo.
- **Un ranking de años de fuego**, y los mismos productos para áreas como Cusco.

### ¿Por qué importa?
Para prevenir incendios hay que saber cómo es lo "normal", y eso exige registros largos. El registro de fuego más largo de NASA (MODIS) está siendo reemplazado por un sensor mejor (VIIRS). Sin un puente entre ambos, las tendencias de largo plazo salen simplemente mal. Y la ventana para construir ese puente se está cerrando: la órbita de MODIS Aqua se está desviando y el satélite S-NPP dejó de entregar datos el 2 de noviembre de 2026.

### ¿Funciona? ⟳
- Entrenamos el traductor solo con 2012–2017 y lo probamos en 2018–2022, años que nunca había visto. Su estimación del total se equivocó apenas un **3.8 %**, y siguió casi perfectamente las subidas y bajadas de cada semana (**correlación 0.98**).
- Un segundo satélite VIIRS, independiente (NOAA-20), coincide con S-NPP en ±5 % por año. Así que el registro puede continuar ahora que S-NPP terminó.
- Lo que aprendimos: la historia reconstruida sugiere que **2005 fue el peor año de fuego en Perú desde 2002** (≈ 101 000 focos en la escala VIIRS de hoy, rango 93 000–106 000). Supera incluso a 2024 (≈ 93 000). En los datos crudos, 2005 parece entre 5 y 9 veces menor. `[[confirmar con climatology/annual_ranking.csv]]`

### ¿Cómo funciona? (detalle técnico)
1. **Datos y limpieza.** Usamos los archivos anuales por país de NASA FIRMS para Perú (productos estándar de calidad científica, no NRT): MODIS Aqua/Terra, VIIRS S-NPP y VIIRS NOAA-20. Pasamos la hora a hora local (UTC-5), quitamos duplicados, dejamos solo fuegos de vegetación (`type = 0`) y descartamos la confianza baja. Una **máscara de fuentes estáticas** quita en todos los años los puntos calientes persistentes que no son vegetación (volcanes, industria, quema de gas). Además corrige una inconsistencia conocida entre versiones de MODIS antes de 2018.
2. **Agregación semanal.** Agrupamos las detecciones por semana ISO y celda de 0.25°, **manteniendo las semanas con cero** (quitarlas sesgaría el modelo hacia arriba). Las semanas sin observación satelital se marcan como faltantes, no como cero.
3. **Calibración con GLM.** La referencia es MODIS **Aqua**, que pasa a ~13:30 como VIIRS. Terra (~10:30) queda fuera. Ajustamos GLM Poisson (conteos) y Tweedie (potencia radiativa del fuego, FRP): `y ~ semana + VIIRS:temporada`, con errores agrupados por semana. El efecto fijo de semana absorbe el clima y el fuego que ambos sensores comparten, así que el coeficiente mide solo la diferencia entre sensores. Se excluyen los apagones documentados (Aqua en ago-2020, S-NPP en jul–ago-2022).
4. **Selección del modelo con años reservados.** Calibramos en 2012–2017 y validamos en 2018–2022. Nos quedamos con el modelo más simple, salvo que uno más complejo baje el error de validación en más de 5 %. Ganó el **modelo por temporada**. Factores finales (2012–2022) ⟳: **4.97× temporada alta (ago–sep), 6.66× media, 8.94× baja** (IC 95 % ≈ ±6 %).
5. **Armonización.** En 2002–2011 el factor se aplica a series *agregadas* de Aqua, nunca a puntos individuales. Desde 2012 se usa VIIRS real: S-NPP, con NOAA-20 en las semanas en que S-NPP falla. Cada semana registra su fuente y una marca de calidad.
6. **Incertidumbre.** Además del intervalo de confianza del factor, hay una **banda de predicción semanal del 90 %**, construida con errores fuera de muestra, que cubre el 88–90 % de las semanas de 2023–2024.
7. **Climatología.** Líneas base mensual y semanal (2003–2024), percentiles empíricos y seis categorías de anomalía. Un mes estimado se marca si su banda de incertidumbre podría cambiarle la categoría.

### ¿Qué esperamos lograr?
`[[ajustar al uso final]]` Dar a gobiernos regionales, brigadas, gestores de áreas protegidas e investigadores de Perú, empezando por Cusco, una línea base confiable para detectar a tiempo quemas anormales, prepararse antes del pico de agosto–septiembre y comprobar con los años si la prevención funciona. Siguientes pasos:
- factores por región (costa / sierra / selva, con la altitud de NASADEM de NASA);
- validación contra el producto de área quemada de MODIS (MCD64A1);
- actualización casi en tiempo real con NOAA-20/NOAA-21;
- el mismo método para cualquier país con archivo de FIRMS.

### Herramientas
Python 3 (pandas, NumPy, statsmodels, Matplotlib, PyYAML, PyArrow), Git/GitHub. `[[frontend]]`

---

## 6. Uso de inteligencia artificial

> Los jueces no lo ven, pero es obligatorio. Revisen que sea fiel a lo que hicieron.

Sí. La idea del proyecto, las decisiones metodológicas (elección de sensores, ventanas de calibración y validación, jerarquía de modelos, tratamiento de ceros, apagones e incertidumbre) y la interpretación de resultados son del equipo. Usamos un asistente de programación con IA (Claude, de Anthropic, vía Claude Code) para ayudar a escribir y reorganizar partes del pipeline en Python, revisar controles de calidad de datos y redactar y traducir al inglés la documentación y estos textos. El equipo revisó y ejecutó todo el código asistido, y cada resultado sale de nuestro pipeline con datos de NASA. La ayuda de IA se reconoce en el README. `[[agregar esa nota en el README]]` No se usan imágenes, audio ni video generados con IA. `[[si se usan, llevan marca de agua visible]]`

---

## 7. Datos de NASA

- **NASA FIRMS**, archivos anuales por país para Perú, productos estándar:
  - MODIS Colección 6.1 Active Fire de **Aqua** y **Terra**, 2002–2024, 1 km;
  - VIIRS 375 m Active Fire de **Suomi NPP**, 2012–2024;
  - VIIRS 375 m Active Fire de **NOAA-20**, 2018–2024.
- Guías de usuario de NASA: MODIS C6 Active Fire y VIIRS C2 Burned Area.
- `[[si se usa]]` **NASADEM** (altitud, 30 m) para las zonas costa/sierra/selva.
- `[[si se usa]]` **MODIS MCD64A1** (área quemada) para validación independiente.

Los datos de NASA son el núcleo: cada número de la historia armonizada, el calendario y el semáforo sale de detecciones de FIRMS.

---

## 8. Datos de otras agencias y referencias

`[[completar con todo lo que se use, imágenes incluidas]]`
- `[[si se usa]]` ESA CCI Land Cover y ESA WorldCover, vía Microsoft Planetary Computer.
- `[[si se usa]]` Copernicus DEM GLO-90 (ESA).
- API STAC de Microsoft Planetary Computer.
- Anuncio de Earthdata/LANCE sobre el fin de S-NPP (nov-2026).
- Software libre: Python, pandas, NumPy, statsmodels, Matplotlib, PyYAML, PyArrow.
- `[[frontend: librerías, mapas base con su atribución, íconos, fuentes]]`

---

## 9. Demo: 7 slides

> Para cualquier público. Una idea por slide, un título que se entienda solo, una imagen grande y como máximo 2–3 líneas de texto. Sin siglas sin explicar. Los detalles técnicos se quedan en la página del proyecto. **Las slides reales van en inglés** (ver submission_en.md).

**Slide 1: Portada**
- **FireCal Perú**: ¿esta temporada de fuego es normal?
- Equipo `[[nombre]]` · `[[integrantes]]` · Reto `[[nombre]]` · NASA Space Apps 2026
- Imagen: mapa de Perú con focos de calor.

**Slide 2: El problema**
- **"¿De verdad explotaron los incendios en 2012?"**
- No. NASA lanzó un satélite más nítido que ve 5–9× más focos.
- El registro antiguo y el nuevo no se pueden comparar, así que se desperdician 20 años de historia.
- Imagen: gráfico crudo con el salto en 2012 (`audit_annual_counts.png`).

**Slide 3: Nuestra idea**
- **Un traductor entre dos satélites.**
- Mientras volaron juntos, aprendimos su "tipo de cambio", temporada por temporada.
- Luego convertimos el registro antiguo a la escala del nuevo.
- Imagen: diagrama simple: satélite antiguo → ×5 a ×9 → satélite nuevo.

**Slide 4: Funciona** ⟳
- **Probado en 5 años que nunca vio: menos de 4 % de error.**
- Un tercer satélite (NOAA-20) confirma el resultado.
- Imagen: línea predicha vs. real (`prediction_vs_snpp.png`).

**Slide 5: El resultado**
- **Una sola historia de fuego para Perú, 2002 → hoy.**
- Hallazgo: 2005 habría sido el peor año de fuego en dos décadas. `[[confirmar]]`
- Imagen: `harmonized_series.png`.

**Slide 6: Cómo lo usa la gente**
- **Una brigada en Cusco mira el calendario: "Este agosto está muy por encima de lo normal."**
- Pueden prepararse antes del pico de incendios.
- Imagen: `calendar_cusco.png` con el semáforo, o una captura de la web.

**Slide 7: Impacto**
- **Prevención de incendios más temprana y basada en evidencia, 100 % con datos abiertos de NASA.**
- Siguiente: precisión por región, actualización en vivo, cualquier país.
- Enlaces: web y GitHub (código QR).

---

## 10. Alternativa: guion de video de 30 s

> Si hablan en español, el video debe llevar **subtítulos en inglés** (los textos están en submission_en.md). Ninguna persona menor de 18 años puede aparecer.

| Tiempo | Imagen | Narración (ES) |
|---|---|---|
| 0:00–0:03 | Logo del equipo | "Somos el equipo `[[nombre]]`, de Perú." |
| 0:03–0:08 | Gráfico crudo con el salto de 2012 | "¿Explotaron los incendios en Perú en 2012? No. NASA lanzó un satélite más nítido." |
| 0:08–0:11 | Título | "FireCal Perú: una historia de fuego, dos satélites." |
| 0:11–0:21 | Diagrama del traductor → serie armonizada | "Le enseñamos al satélite antiguo a hablar el idioma del nuevo, lo probamos en años que nunca vio y reconstruimos 22 años de incendios." |
| 0:21–0:30 | Calendario de Cusco y web | "Ahora cualquiera puede saber si esta temporada es normal y actuar a tiempo. Todo con datos abiertos de NASA." |
