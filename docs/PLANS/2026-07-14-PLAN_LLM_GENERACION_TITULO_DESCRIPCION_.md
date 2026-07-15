# Plan: Generación de título y descripción de propiedades con LLM local

## Objetivo

Generar el **título** y la **descripción** de una propiedad a partir de su draft (características
estructuradas), usando un LLM local (decisión D5: sin APIs externas) que corra en el VPS
(6 cores, 12 GB RAM) sin saturarlo. Esta primera iteración cubre únicamente la **fase de
experimentación en local** con notebooks.

## Modelo seleccionado

**Qwen3-4B-Instruct-2507**, GGUF cuantizado **Q4_K_M** (~2.5 GB), descargado del repo público
`unsloth/Qwen3-4B-Instruct-2507-GGUF` en Hugging Face.

Presupuesto de RAM estimado: pesos ~2.5 GB + KV cache @ 8K contexto ~1.2 GB (144 KB/token,
36 capas, GQA 8 cabezas KV, dim 128) + overhead ~0.4 GB ≈ **3.5–4.2 GB**. En el VPS de 12 GB
deja margen para RabbitMQ, MLflow y los demás servicios.

Runtime de experimentación: `llama-cpp-python` (mismo GGUF que usará `llama-server` en
producción). Salida estructurada con JSON schema (gramática) para garantizar
`{"titulo", "descripcion"}` válido por construcción.

## Alcance

**Incluido (esta iteración):**
- `notebooks/llm/requirements.txt` — dependencias propias de los experimentos.
- `notebooks/llm/01_descarga_y_benchmark_qwen3.ipynb` — descarga del GGUF a
  `models_registry/llm/`, carga en RAM con medición, smoke test y benchmark de tokens/s.
- `notebooks/llm/02_generacion_titulo_descripcion.ipynb` — draft → prompt, system prompt v1
  con regla anti-invención, salida estructurada, corrida sobre `notebooks/testbench.csv`
  (23 propiedades), experimento de temperatura y checklist de evaluación manual.

**Excluido (fases futuras):**
- Cambios en `src/llm_local_service` (worker consumidor de `llm_queue`, callback de resultados).
- Contenedor `llama-server` y su Dockerfile.
- Benchmark en el VPS.
- Registro del prompt/config ganador en MLflow.
- Enriquecimiento del esquema del draft (ubicación, amenidades con nombre) — hoy el testbench
  sintético solo trae conteos, por lo que las descripciones salen genéricas.

## Cambios por capa

- **Notebooks (experimentación):** carpeta nueva `notebooks/llm/` con los dos notebooks y su
  `requirements.txt`. Se instala sobre el `.venv` existente de `notebooks/`.
- **Modelos:** el GGUF vive en `models_registry/llm/` (ya ignorado por git vía
  `models_registry/*`), el mismo directorio que el VPS monta como volumen
  (`MODELS_REGISTRY_HOST`).
- **Servicios (src/):** sin cambios en esta iteración.

## Dependencias

- `llama-cpp-python` (compila llama.cpp; requiere cmake/gcc), `huggingface_hub`, `pandas`, `psutil`.
- `notebooks/testbench.csv` (23 drafts sintéticos derivados de `properties_synthetic_v1.csv`).

## Pasos de implementación

1. ✅ Crear `notebooks/llm/requirements.txt` e instalar en `notebooks/.venv`.
2. ✅ Notebook 01: descarga idempotente del GGUF, carga (`n_ctx=8192`, `n_threads=6` local /
   5 en VPS), medición de RAM, smoke test en español y benchmark (prompt processing y
   generación por streaming, 3 corridas).
3. ✅ Notebook 02: conversión draft → texto en español, system prompt v1, generación con
   `response_format` + JSON schema, corrida completa del testbench →
   `notebooks/llm/resultados_testbench.csv`, comparación de temperaturas (0.3/0.7/1.0).
4. ⬜ Revisión manual de resultados (checklist en el notebook 02) e iteración del prompt (v2…).
5. ⬜ Fase siguiente: repetir benchmark en el VPS y, con números reales, planear el worker +
   `llama-server` en un plan nuevo.

## Criterio de decisión

Con **≥5 tokens/s de generación en el VPS**, un anuncio de ~300 tokens sale en ≤60 s y el flujo
asíncrono existente (FastAPI → RabbitMQ `llm_queue` → worker con prefetch=1) lo absorbe sin
saturar el servidor. Por debajo de eso, evaluar Llama 3.2 3B (Q4, ~1.9 GB) o Qwen3-1.7B.

---

## Fase 2 (2026-07-14): Grafo de conocimiento del dominio — notebook 03

Resultados de la fase 1 en local: JSON válido garantizado, ~35 s por anuncio (2 threads,
confirmando que el cuello es ancho de banda de memoria), español natural, pero **invención leve
de entorno** ("zona residencial", "buen acceso") en todas las temperaturas.

**Estrategia** (asesoría del supervisor): modelar el dominio en un **grafo de conocimiento**
(NetworkX, ~40 nodos iniciales, serializado a `notebooks/llm/grafo_dominio.json`) que provee al
modelo *poco contexto pero bien limitado* — una **whitelist curada** de hechos y ángulos
narrativos (amenidad → tema → frases aprobadas, tipo de propiedad → narrativa, operación → tono,
reglas → audiencia) en lugar de solo prohibir invenciones.

**Esquema real del draft** (API transaccional): JSON anidado con `propertyType.name`,
`address.neighborhoodName`, `availableToRent` (true=renta, false=venta), `amenities` con nombre,
`listedPrice`, etc. Ejemplos en `notebooks/llm/drafts_ejemplo.json`.

**Reglas duras nuevas (negocio):**
- **Nunca mencionar precios/montos** — el detector de anomalías marcaría el anuncio. Por diseño,
  `listedPrice` no entra al contexto del modelo.
- **Nunca lenguaje de contacto, urgencia ni llamados a la acción.** Puramente la propiedad.
- **Ubicación = solo nombre de colonia** (sin calle/números, sin atributos de la zona; el grafo
  no modela ubicaciones por decisión del usuario).

**Artefactos fase 2:**
- `notebooks/llm/03_grafo_dominio_inferencia.ipynb` — construcción del grafo, parser del draft
  real, consulta `contexto_desde_grafo()`, prompt v3, A/B v2 vs v3 con verificación programática
  (regex) de cero precios y cero contacto → `resultados_ab_grafo.csv`.
- `notebooks/llm/drafts_ejemplo.json` — 7 drafts con el esquema real (renta/venta, casa/depto/loft,
  a estrenar/antigua, amenidades desconocidas y sin amenidades).
- `notebooks/llm/grafo_dominio.json` — grafo serializado (node-link), candidato a artefacto
  versionado en MLflow para que lo cargue el worker en producción.

**Fuera de alcance fase 2:** minar Properati automáticamente (sus descripciones reales traen
teléfonos y precios, violan las reglas nuevas), capa de ubicaciones en el grafo, cambios en
`src/llm_local_service`.

---

## Fase 3 (2026-07-15): Grafo de inferencia ponderado (v4) — `notebooks/graph-ai/`

Resultados fase 2 (ver `notebooks/llm/METRICAS.md`): v3-1.7B es 2× más rápido (12.9 s vs 26.1 s)
pero con calidad ≈ 4B sin grafo (clichés ocasionales). Nueva estrategia (asesoría del
supervisor): el grafo deja de *recuperar contexto* y pasa a **decidir** — narrativa, tono,
audiencia, temas (top-2) y amenidades prioritarias se resuelven con **propagación ponderada**
(pesos 0.3/0.6/0.9, priors ≤ 0.8, bloqueos −10 como reglas de negocio) y el LLM recibe solo un
resumen prescriptivo (~100 tokens) que obedece.

**Artefactos fase 3:**
- `notebooks/graph-ai/init.md` — concepto y metodología del grafo ponderado.
- `notebooks/graph-ai/datasets/` — la única fuente del dominio, sincronizada con la BD
  transaccional real (22 amenidades, 6 tipos incl. comerciales, 11 temas, 7 audiencias,
  80 aristas, 9 bloqueos). CSVs editables por negocio; README con metodología de elicitación.
- `notebooks/graph-ai/motor_inferencia.py` — motor determinista (cargar/validar dominio,
  activación con buckets, propagación, selección, traza auditable, resumen para LLM).
  Lo reutilizará el worker.
- `notebooks/graph-ai/test_motor.py` — 67 tests (decisión, bloqueos exhaustivos, validación
  de carga). Correr antes de cualquier cambio de pesos.
- `notebooks/graph-ai/generar_visualizador.py` → `grafo_vivia.html` — visualizador interactivo
  con simulador de drafts (especificación visual del motor).
- `notebooks/graph-ai/01_grafo_ponderado.ipynb` — trazas de decisión, prompt v4 ("obedecer,
  no elegir") y A/B v4-4B / v4-1.7B contra baselines v3 → `resultados_v4.csv`.

**Criterio de decisión fase 3:** si v4-1.7B logra 0 violaciones, ~520 tokens de prompt y
calidad indistinguible de v3-4B en lectura manual → es el modelo del worker (RAM ~2.3 GB,
~11 s/anuncio local, ~20-25 s estimado en VPS). Siguiente fase: benchmark en VPS + worker de
`llm_queue` consumiendo `motor_inferencia.py` + `datasets/` + GGUF como artefactos versionados.
