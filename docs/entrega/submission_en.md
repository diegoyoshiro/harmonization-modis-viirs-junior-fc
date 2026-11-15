# Entrega Space Apps 2026: textos en inglés (borrador vivo)

> Nota interna, en español: este archivo reúne los textos de la página del proyecto, las 7 slides y el guion del video. **Todo lo que se pega en la web de Space Apps va en inglés.** La traducción para el equipo está en [submission_es.md](submission_es.md); si cambian algo aquí, cámbienlo también allá.
> - Lo que está entre `[[ ]]` es un dato pendiente o una nota del equipo. Bórralo antes de pegar.
> - Las cifras salen de `output/processed/` (corrida actual: modelo B, factores 2012–2022). Si se vuelve a correr `calibrate`, `harmonize` o `climatology`, actualiza las cifras marcadas con ⟳.
> - Cierre del envío: **domingo 15-nov-2026, 23:59 hora del evento local**. Guarden la página a menudo ("Save Progress").
>
> **Niveles de lectura** (de lo más simple a lo más técnico):
> 1. Slides / video → cualquier persona. Una idea por slide y sin jerga.
> 2. Summary → un párrafo sin jerga.
> 3. Detailed Description → empieza en lenguaje simple y termina con el detalle técnico. Ese detalle es lo que puntúa en **Validity** (base científica).

---

## 1. Project Name

**FireCal Peru: one fire record, two NASA satellites, 22 years**

Alternativas:
- *Burning Calendar Peru: is this fire season normal?*
- *Two Satellites, One Fire Record*

---

## 2. High-Level Project Summary

NASA satellites have watched fires in Peru for over 20 years, but with two different instruments. The newer one (VIIRS, since 2012) is much sharper and sees 5 to 9 times more fires than the older one (MODIS, since 2002). If you put both records together, it looks as if fires exploded in 2012, but that jump is only the new instrument. We fixed this. During the years both satellites flew together, we learned the "exchange rate" between them, season by season. We tested it on years it had never seen, then used it to convert the old record into the new one's scale. The result is a single, comparable fire history for Peru from 2002 to today, with honest error margins. On top of it we built a burning calendar and a "traffic light" that tells fire brigades, local authorities and researchers, starting in Cusco, whether this month's fire activity is normal or alarming.

---

## 3. Link to Project Demo

`[[enlace público a las slides (Google Slides/PDF) o al video de YouTube ≤ 30 s; probarlo en ventana privada]]`

---

## 4. Link to Final Project

`[[sitio web]]`, `https://github.com/diegoyoshiro/harmonization-modis-viirs-junior-fc`

`[[El repo debe ser público. Verificar que el README tenga un resumen en inglés.]]`

---

## 5. Detailed Project Description

### In plain words
Imagine comparing today's photos, taken with a phone camera, with old photos from a cheap camera: you see more detail today, but that doesn't mean there's more to see. Fire satellites have the same problem. We built a "translator" between NASA's old and new fire sensors, so Peru finally has one fire history that can be compared year by year since 2002.

### What does it do?
- **One harmonized fire history** for Peru (2002–2024), weekly, monthly and yearly, also on a map grid. Every value is labeled *estimated* (2002–2011, translated from the old sensor) or *observed* (2012 onward), and comes with an error margin.
- **A burning calendar** (year × month) that shows when the fire season starts, peaks (August–September) and ends.
- **A "traffic light" of anomalies**: each month is compared with the 2003–2024 normal and classified from "well below normal" to "extreme". The colors are colorblind-friendly.
- **A ranking of fire years**, and the same products for areas such as Cusco.

### Why does it matter?
To prevent fires you need to know what "normal" looks like, and that takes long records. NASA's longest fire record (MODIS) is being replaced by a better sensor (VIIRS). Without a bridge between them, long-term trends are simply wrong. The window to build that bridge is closing: MODIS Aqua's orbit is drifting, and the S-NPP satellite stopped delivering data on 2 November 2026.

### Does it work? ⟳
- We trained the translator on 2012–2017 only and tested it on 2018–2022, years it had never seen. Its estimate of the total missed by just **3.8 %**, and it followed the week-to-week ups and downs almost perfectly (**correlation 0.98**).
- A second, independent VIIRS satellite (NOAA-20) agrees with S-NPP within about ±5 % per year. So the record can continue now that S-NPP has ended.
- What we learned: the rebuilt history suggests **2005 was Peru's worst fire year since 2002** (≈ 101,000 detections in today's VIIRS scale, range 93k–106k). That is even above 2024 (≈ 93,000). On the raw data, 2005 looks 5–9 times smaller. `[[confirmar con climatology/annual_ranking.csv]]`

### How does it work? (technical details)
1. **Data and cleaning.** We use the NASA FIRMS annual country archives for Peru (standard, science-quality products, not NRT): MODIS Aqua/Terra, VIIRS S-NPP and VIIRS NOAA-20. We convert times to local time (UTC-5), remove duplicates, keep vegetation fires only (`type = 0`) and drop low-confidence detections. A **static-source mask** removes persistent non-vegetation hotspots (volcanoes, industry, gas flares) in all years. It also corrects a known inconsistency between MODIS collection versions before 2018.
2. **Weekly aggregation.** Detections are grouped by ISO week and 0.25° cell, **keeping explicit zero weeks** (dropping them would bias the model upward). Weeks without satellite observations are flagged as missing, not counted as zero.
3. **Calibration with GLMs.** The reference is MODIS **Aqua**, which passes at ~13:30 like VIIRS. Terra (~10:30) is excluded. We fit Poisson GLMs (counts) and Tweedie GLMs (fire radiative power): `y ~ week + VIIRS:season`, with standard errors clustered by week. The week fixed effects absorb the weather and fire conditions both sensors share, so the coefficient captures only the sensor difference. Documented outages (Aqua Aug 2020, S-NPP Jul–Aug 2022) are excluded.
4. **Model selection on held-out years.** We calibrate on 2012–2017 and validate on 2018–2022. We keep the simplest model unless a more complex one lowers the validation error by more than 5 %. The **seasonal model** won. Final factors (2012–2022) ⟳: **4.97× high season (Aug–Sep), 6.66× mid season, 8.94× low season** (95 % CI ≈ ±6 %).
5. **Harmonization.** For 2002–2011 the factor is applied to *aggregated* Aqua series, never to individual points. From 2012 we use real VIIRS: S-NPP, with NOAA-20 filling S-NPP gaps. Each week records its source and a quality flag.
6. **Uncertainty.** Besides the factor's confidence interval, an empirical **90 % weekly prediction band** built from out-of-sample errors covers 88–90 % of weeks in 2023–2024.
7. **Climatology.** Monthly and weekly baselines (2003–2024), empirical percentiles and six anomaly categories. An estimated month is flagged when its uncertainty band could change its category.

### What do we hope to achieve?
`[[ajustar al uso final]]` Give regional governments, fire brigades, protected-area managers and researchers in Peru, starting with Cusco, a reliable baseline to spot abnormal burning early, prepare before the August–September peak, and check whether prevention works over the years. Next steps:
- region-specific factors (coast / Andes / Amazon, from NASA's NASADEM elevation data);
- validation against NASA's MODIS Burned Area product (MCD64A1);
- near-real-time updates with NOAA-20/NOAA-21;
- the same method for any country with a FIRMS archive.

### Tools
Python 3 (pandas, NumPy, statsmodels, Matplotlib, PyYAML, PyArrow), Git/GitHub. `[[frontend: framework/hosting de la página web]]`

---

## 6. Use of Artificial Intelligence (AI)

> Este campo no lo ven los jueces, pero es obligatorio. `[[revisar que describa lo que realmente hizo el equipo]]`

Yes. The project idea, the methodological decisions (sensor choice, calibration and validation windows, model hierarchy, treatment of zeros, outages and uncertainty) and the interpretation of results come from our team. We used an AI coding assistant (Claude, by Anthropic, via Claude Code) to help write and refactor parts of the Python pipeline, review data-quality checks, and draft and translate documentation and these submission texts into English. All AI-assisted code was reviewed and run by the team, and every result reported here was produced by our pipeline from NASA data. AI assistance is acknowledged in the repository README. `[[agregar esa nota en el README]]` No AI-generated images, audio or video are used. `[[si se usan, deben llevar marca de agua visible]]`

---

## 7. NASA Data

- **NASA FIRMS (Fire Information for Resource Management System)**, annual country archives for Peru, standard (science-quality) products:
  - MODIS Collection 6.1 Active Fire from **Aqua** and **Terra**, 2002–2024, at 1 km;
  - VIIRS 375 m Active Fire from **Suomi NPP**, 2012–2024;
  - VIIRS 375 m Active Fire from **NOAA-20 (JPSS-1)**, 2018–2024.
  - Source: https://firms.modaps.eosdis.nasa.gov/
- NASA user guides used to interpret the data: *MODIS Collection 6 Active Fire Product User's Guide* and *VIIRS Collection 2 Burned Area User's Guide*.
- `[[si se usa]]` **NASADEM** (30 m elevation) to define coast / Andes / Amazon zones.
- `[[si se usa]]` **MODIS Burned Area MCD64A1** for independent validation.

NASA data is the core of the project: every number in the harmonized history, calendar and traffic light comes from FIRMS detections.

---

## 8. Space Agency Partner Data & Other References

`[[completar con todo lo que se use; las imágenes también cuentan]]`
- `[[si se usa]]` ESA Climate Change Initiative Land Cover and ESA WorldCover, via Microsoft Planetary Computer.
- `[[si se usa]]` Copernicus DEM GLO-90 (ESA).
- Microsoft Planetary Computer STAC API (data access).
- NASA Earthdata/LANCE announcement on the end of S-NPP data delivery (Nov 2026).
- Open-source software: Python, pandas, NumPy, statsmodels, Matplotlib, PyYAML, PyArrow.
- `[[frontend: librerías, mapas base (p. ej. OpenStreetMap, con su atribución), íconos, fuentes]]`
- `[[referencias bibliográficas, si las citan]]`

---

## 9. Project Demo: 7 slides

> Para cualquier público. Una idea por slide, un título que se entienda solo, una imagen grande y como máximo 2–3 líneas de texto. Sin siglas sin explicar. Los detalles técnicos se quedan en la página del proyecto.
> Elementos obligatorios: nombre del equipo, integrantes, reto, imagen del proyecto, experiencia de uso y datos de NASA.

**Slide 1: Title**
- **FireCal Peru**: Is this fire season normal?
- Team `[[nombre]]` · `[[integrantes]]` · Challenge: `[[nombre exacto del reto]]` · NASA Space Apps 2026
- Visual: a map of Peru with fire hotspots.

**Slide 2: The problem**
- **"Did fires really explode in 2012?"**
- No. NASA launched a sharper satellite that sees 5–9× more fires.
- Old and new records can't be compared, so 20 years of history are wasted.
- Visual: raw chart with the jump in 2012 (`audit_annual_counts.png`).

**Slide 3: Our idea**
- **A translator between two satellites.**
- While both flew together, we learned their "exchange rate", season by season.
- Then we converted the old record into the new one's scale.
- Visual: a simple diagram: old satellite → ×5 to ×9 → new satellite.

**Slide 4: It works** ⟳
- **Tested on 5 years it had never seen: less than 4 % off.**
- A third satellite (NOAA-20) confirms the result.
- Visual: predicted vs real line (`prediction_vs_snpp.png`).

**Slide 5: The result**
- **One fire history for Peru, 2002 → today.**
- Insight: 2005 was likely the worst fire year in two decades. `[[confirmar]]`
- Visual: `harmonized_series.png`.

**Slide 6: How people use it**
- **A fire brigade in Cusco checks the calendar: "This August is far above normal."**
- They can prepare before the fire peak.
- Visual: `calendar_cusco.png` with the traffic light, or a screenshot of the web page.

**Slide 7: Impact**
- **Earlier, evidence-based fire prevention, built 100 % on free NASA data.**
- Next: region-by-region accuracy, live updates, any country.
- Links: website and GitHub (QR code).

---

## 10. Alternativa: guion de video de 30 s

> Solo si eligen video en lugar de slides. Si hablan en español, deben ir **subtítulos en inglés**. Ninguna persona menor de 18 años puede aparecer.

| Tiempo | Imagen | Narración / subtítulo (EN) |
|---|---|---|
| 0:00–0:03 | Logo del equipo | "We're team `[[name]]`, from Peru." |
| 0:03–0:08 | Gráfico crudo con el salto de 2012 | "Did Peru's fires explode in 2012? No. NASA just launched a sharper satellite." |
| 0:08–0:11 | Título | "FireCal Peru: one fire history, two satellites." |
| 0:11–0:21 | Diagrama traductor → serie armonizada | "We taught the old satellite to speak the new one's language, tested it on years it never saw, and rebuilt 22 years of fires." |
| 0:21–0:30 | Calendario de Cusco y web | "Now anyone can see if this fire season is normal, and act in time. All with free NASA data." |
