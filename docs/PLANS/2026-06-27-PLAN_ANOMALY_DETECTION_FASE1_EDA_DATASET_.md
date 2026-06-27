# Plan: Fase 1 — EDA y Dataset Artificial (Isolation Forest)

## Objetivo

Montar el entorno Jupyter aislado en `notebooks/`, explorar los datasets de Properati MX
disponibles en `datasets/`, y generar el dataset artificial alineado al esquema `Draft` que
servirá de insumo de entrenamiento para el modelo Isolation Forest.

Esta fase cubre los pasos 0–1b del plan principal
(`2026-06-27-PLAN_ANOMALY_DETECTION_ISOLATION_FOREST_.md`).

## Alcance

### Incluido
- Entorno Jupyter aislado (Docker o venv local en `notebooks/`).
- EDA de los CSV de Properati MX (renta + venta) en `notebooks/01_data_extraction_and_eda.ipynb`.
- Mapeo de columnas externas → esquema `Draft`.
- Extracción de parámetros reales (medias, std, rangos por `property_type`).
- Generación del dataset artificial en `notebooks/02_synthetic_dataset.ipynb`.
- Inyección de anomalías sintéticas marcadas (`is_anomaly=True`) para validación posterior.
- Persistencia en `datasets/properties_synthetic_v1.parquet`.

### Excluido
- Feature engineering (`features.py`) — fase siguiente.
- Entrenamiento del modelo — fase siguiente.
- Carga del modelo / inferencia real — fases posteriores.

## Datos disponibles

| Archivo | Tamaño | Tipo |
|---|---|---|
| `datasets/properati-MX-2016-11-01-properties-rent.csv` | ~40 MB | Renta |
| `datasets/properati-MX-2016-11-01-properties-sell.csv` | ~185 MB | Venta |

## Cambios por capa

### Entorno — `notebooks/requirements-dev.txt`
Agregar `pyarrow` y `jupyterlab` (faltaban para Parquet y JupyterLab UI).

### EDA — `notebooks/01_data_extraction_and_eda.ipynb`
- Carga de ambos CSV, exploración de nulos, distribuciones, correlaciones.
- Mapeo de columnas Properati → `Draft`.
- Extracción de parámetros por `property_type`.

### Dataset artificial — `notebooks/02_synthetic_dataset.ipynb` (nuevo)
- Generación de registros normales calibrados con los parámetros del EDA.
- Inyección de anomalías sintéticas (≈3-5%).
- Guardado en `datasets/properties_synthetic_v1.parquet`.

## Mapeo columnas Properati → Draft

| Campo `Draft` | Columna Properati | Transformación |
|---|---|---|
| `areaM2` | `surface_total_in_m2` | float, dropna |
| `listedPrice` | `price_aprox_local_currency` | float MXN |
| `pricePerM2` | `price_per_m2` | derivar si nulo |
| `bedrooms` | `rooms` | int, imputar mediana |
| `bathrooms` | — | ratio derivado por tipo |
| `parkingSpaces` | — | imputar 0/1 por tipo |
| `propertyType.name` | `property_type` | mapeo de valores |
| `address.postalCode` | `place_name` | proxy de zona |
| `constructionYear` | — | distribución por tipo |

## Pasos de implementación

1. Actualizar `notebooks/requirements-dev.txt` con `pyarrow` y `jupyterlab`.
2. Poblar `notebooks/01_data_extraction_and_eda.ipynb` con EDA completo.
3. Crear `notebooks/02_synthetic_dataset.ipynb` con generación y persistencia del dataset.

## Verificación

- EDA completa sin errores; muestra distribuciones y diccionario `params` con medias/std.
- `datasets/properties_synthetic_v1.parquet` existe con ≥5 000 filas normales + bloque de anomalías.
- `df['is_anomaly'].value_counts()` refleja la proporción inyectada (≈3-5%).
- Sin nulos en las columnas de features principales.

## Pasos siguientes

| Paso | Descripción | Archivo |
|---|---|---|
| 3 | Feature engineering compartido | `src/anomaly_detector_api/training/features.py` |
| 4 | Entrenamiento Isolation Forest | `src/anomaly_detector_api/training/train_isolation_forest.py` |
| 5 | Carga real del modelo | `shared/model_loader.py` |
| 6 | Settings del umbral y nombre del modelo | `config/settings.py` |
| 7 | Inferencia real (reemplazar `approved=True`) | `src/anomaly_detector_api/usecases/analyze_property.py` |
