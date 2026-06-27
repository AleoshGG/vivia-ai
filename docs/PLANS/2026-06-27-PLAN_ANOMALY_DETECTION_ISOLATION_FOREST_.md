# Plan: Detección de Anomalías de Propiedades (Isolation Forest multivariable)

## Objetivo

Montar el primer modelo de ML real que aporte valor tangible al cliente desde el móvil.
Tras analizar las 4 propuestas contra los criterios del usuario (impacto/respuesta
tangible, generación de datos, dificultad), gana **Detección de Anomalías** porque:

1. **Impacto/respuesta tangible**: el flujo "el móvil publica un `Draft` → `vivia-ai`
   analiza → callback con `{ draftId, approved, reason }`" **ya está cableado** en
   [analyze_property.py](../../src/anomaly_detector_api/usecases/analyze_property.py), pero
   hoy devuelve `approved=True` hardcodeado. Solo falta insertarle un modelo real.
2. **Datos**: Isolation Forest es **no supervisado** → no requiere etiquetas. El modelo
   `Draft` ([property.py](../../src/anomaly_detector_api/models/property.py)) ya trae
   features estructuradas y limpias (sin necesidad de NLP ni geocodificación pesada).
3. **Dificultad**: la menor: endpoint, callback, reintentos y modelos Pydantic ya existen.

Decisiones del usuario que ajustan el alcance:
- Modelo **Isolation Forest multivariable** (no solo precio).
- **NLP de título/descripción queda FUERA** (fase futura).
- **No existen drafts reales** → se parte de un **dataset externo real** (descargado de
  fuera, p.ej. listados inmobiliarios MX públicos / Kaggle / portal) sobre el que se hace
  un **EDA**, y luego se **transforma** en el **dataset artificial** que será el que
  realmente entrene el modelo (alineado al esquema `Draft`).

## Alcance

### Incluido
- **Ingesta de un dataset externo real** de propiedades como fuente de calibración.
- **EDA** del dataset externo (distribuciones, rangos, correlaciones, nulos, outliers).
- **Transformación** del dataset externo → **dataset artificial** alineado al esquema
  `Draft`, que es el insumo de entrenamiento (no se entrena con datos inventados de cero,
  sino con datos derivados/calibrados de la realidad).
- **Feature engineering** desde el modelo `Draft` (solo features estructuradas/numéricas).
- Entrenamiento de **Isolation Forest** (notebook + script reproducible) y persistencia
  del modelo + artefactos de preprocesamiento.
- Carga del modelo en el servicio e **inferencia real** dentro de `analyze_property.py`,
  reemplazando el `approved=True` simulado, conservando el flujo de callback/reintentos.
- `reason` explicable (qué features dispararon la anomalía).

### Excluido
- NLP de título/descripción (fase posterior).
- Procesamiento de imágenes/`mediaFiles`.
- Geocodificación a lat/long y features de distancia (Google Places, INEGI).
- Reentrenamiento automático / pipeline de drift.

## Features para el modelo (desde `Draft`)

Numéricas directas: `areaM2`, `bedrooms`, `bathrooms`, `parkingSpaces`,
`constructionYear` (→ derivar `antiguedad = año_actual - constructionYear`),
`listedPrice`, `pricePerM2`.
Derivadas: `n_amenities = len(amenityIds)`, `condominium` (bool→int),
`total_images` / ratio de archivos.
Categóricas (one-hot o target encoding ligero): `propertyType.name`,
`address.neighborhoodId` (o `postalCode` como proxy de zona).

> Nota de calidad: el riesgo residual es que el vendedor declare m² inflados; Isolation
> Forest lo capta justamente como anomalía en la relación `areaM2`↔`listedPrice`↔zona.

## Cambios por capa

### 1a. Ingesta + EDA del dataset externo — `notebooks/01_data_extraction_and_eda.ipynb` (existente)
- Descargar/ubicar un **dataset externo real** de propiedades (listados MX públicos /
  Kaggle / export de portal) y cargarlo en el data lake local
  ([local_repository.py](../../data_lake/local_repository.py)) bajo `datasets/external_raw/`.
- **EDA**: distribuciones y rangos de precio, m², recámaras/baños, pricePerM2 por
  tipo y zona; correlaciones; % de nulos; detección de outliers. El objetivo es
  **extraer los parámetros reales** (medias, varianzas, correlaciones, rangos por
  `propertyType`/zona) que calibrarán el dataset artificial.
- Documentar el mapeo de columnas externas → campos del esquema `Draft`.

### 1b. Transformación → dataset artificial — `notebooks/02_synthetic_dataset.ipynb` (nuevo) + `src/anomaly_detector_api/training/generate_dataset.py` (nuevo)
- **Transformar** el dataset externo al esquema `Draft`: renombrar/derivar columnas,
  imputar/limpiar según hallazgos del EDA, y **muestrear/aumentar** usando los
  parámetros reales extraídos (no distribuciones inventadas) para obtener el
  **dataset artificial de entrenamiento** del tamaño deseado.
- Inyectar un % pequeño de anomalías sintéticas (precio fuera de rango, m² imposibles,
  pricePerM2 incoherente) **solo para validar** que el modelo las detecta (no para entrenar).
- Guardar como Parquet vía el Repository bajo `datasets/properties_synthetic_v1.parquet`.

### 2. Feature engineering — `src/anomaly_detector_api/training/features.py` (nuevo)
- Función pura `build_feature_frame(drafts) -> DataFrame` reutilizable por entrenamiento
  e inferencia (misma transformación → evitar train/serve skew).
- `PropertyFeatureTransformer`: imputación (mediana por `propertyType`), escalado
  (StandardScaler), encoding de categóricas. Se persiste junto al modelo.

### 3. Entrenamiento — `notebooks/01_data_extraction_and_eda.ipynb` (existente) + `src/anomaly_detector_api/training/train_isolation_forest.py` (nuevo)
- Entrenar `sklearn.ensemble.IsolationForest` (`contamination` calibrado, p.ej. 0.03–0.05).
- Evaluar contra las anomalías sintéticas inyectadas (precision/recall de detección).
- Persistir `model.joblib` + `transformer.joblib` en `models_registry/anomaly/` y, si
  MLflow está disponible, loguear vía la integración de
  [model_loader.py](../../shared/model_loader.py) (hoy es stub → implementar carga local
  como fallback).

### 4. Carga del modelo — `shared/model_loader.py` (modificar)
- Implementar carga real: intentar MLflow; si no, cargar desde `models_registry/` local
  con `joblib`. Devolver `(model, transformer)`. Cachear en memoria (cargar una vez).

### 5. Inferencia — `src/anomaly_detector_api/usecases/analyze_property.py` (modificar)
- Reemplazar el bloque simulado (`asyncio.sleep(2)` + `approved=True`) por:
  1. `build_feature_frame([request.draft])` → vector.
  2. `model.decision_function` / `predict` → score de anomalía.
  3. Mapear a `approved` (umbral) y construir `reason` explicable
     (p.ej. "pricePerM2 fuera del rango esperado para la zona").
- **Conservar intacto** todo el flujo de `_post_result` (callback, reintentos, fallback).
- Como la inferencia sklearn es síncrona y rápida, ejecutarla con
  `await asyncio.to_thread(...)` para no bloquear el event loop.

### 6. Config — `config/settings.py` (modificar)
- Agregar `anomaly_model_name` y `anomaly_score_threshold` (configurables vía `.env`).

### 7. Dependencias — `src/anomaly_detector_api/requirements.txt`
- Agregar `scikit-learn`, `pandas`, `numpy`, `joblib`, `pyarrow`. (`httpx` ya está.)

## Dependencias
- `features.py` es compartido entre training (paso 2/3) e inferencia (paso 5).
- `analyze_property.py` depende de `model_loader.py` ya implementado (paso 4 antes que 5).
- Todo el flujo HTTP/callback existente se reutiliza sin cambios.

## Pasos de implementación
0. Ingestar el dataset externo real y hacer EDA en `01_data_extraction_and_eda.ipynb`;
   extraer parámetros reales y el mapeo de columnas → `Draft`.
1. Crear `training/generate_dataset.py` + notebook → transformar el externo en el dataset
   artificial calibrado (v1) y guardarlo en el data lake local.
2. Crear `training/features.py` (transformación compartida + transformer persistible).
3. Crear `training/train_isolation_forest.py` → entrenar, evaluar vs anomalías inyectadas,
   persistir modelo + transformer en `models_registry/anomaly/`.
4. Implementar carga real en `shared/model_loader.py` (MLflow con fallback local).
5. Añadir settings (`anomaly_model_name`, `anomaly_score_threshold`).
6. Reescribir inferencia en `analyze_property.py` (features → score → approved/reason,
   vía `asyncio.to_thread`), conservando callback/reintentos.
7. Actualizar `requirements.txt`.

## Verificación
- **Dataset**: ejecutar el notebook/script y confirmar que se generan N filas con
  distribuciones coherentes + el bloque de anomalías inyectadas.
- **Modelo**: el reporte de evaluación detecta ≥X% de las anomalías sintéticas con bajo
  falso positivo sobre las normales.
- **Servicio E2E**: levantar `anomaly_detector_api`, hacer `POST /analyze` desde `/docs`
  con (a) un draft normal → `approved=true`, (b) un draft con precio absurdo →
  `approved=false` con `reason` explicable; verificar que el callback a
  `/internal/validations/anomaly/result` se dispara con el payload correcto.
- **No bloqueo**: confirmar que la inferencia no congela el event loop (peticiones
  concurrentes responden).

## Futuro (fuera de este plan)
- Microservicio/etapa NLP para `title` + `description` que aporte features de texto.
- Reentrenar con drafts reales conforme se acumulen y retirar el dataset sintético.
- Features geoespaciales (distancias a servicios) cuando se geocodifiquen direcciones.
