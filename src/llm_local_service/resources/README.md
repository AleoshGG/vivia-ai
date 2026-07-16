# Recursos de producción del LLM Local Service

Artefactos versionados que usa la inferencia real: el **grafo ponderado v4** y el
**prompt v6**. Son la copia de producción de lo validado en el laboratorio
(`notebooks/graph-ai/`) — producción NUNCA importa desde `notebooks/`.

## Contenido

- `graph/` — los 10 CSVs del grafo ponderado v4 (amenidades, temas, audiencias,
  operaciones, tipos de propiedad, buckets, pesos y bloqueos). Fuente:
  `notebooks/graph-ai/datasets/`.
- `prompts/system_prompt_v6.txt` — system prompt v6 (el LLM solo ve las
  inferencias del grafo). Fuente: `SYSTEM_PROMPT_V6` en
  `notebooks/graph-ai/prompt.py`.
- `prompts/output_schema.json` — contrato de salida del anuncio
  (`{"titulo", "descripcion"}`). En v6 el servidor no fuerza gramática; el
  formato se pide por prompt y se valida al parsear.

## Flujo de sincronización notebook → producción → MLflow

1. **Laboratorio**: los cambios al grafo o al prompt se experimentan y
   benchmarkean en `notebooks/graph-ai/` (nunca directo aquí).
2. **Producción**: cuando una versión queda validada, se copian los CSVs y el
   prompt a este directorio (actualizando el sufijo de versión del prompt).
3. **Versionado**: se corre `python -m scripts.upload_llm_model` (sube el GGUF
   al bucket de GCS si cambió) y `python -m scripts.register_llm_generator`
   (registra estos artefactos + metadata como nueva versión de
   `llm-listing-generator` en MLflow y la promueve a `Production`).

El GGUF servido (`Qwen3-1.7B-Q4_K_M.gguf`) vive en `models_registry/llm/` y
respaldado en `gs://<bucket>/models_registry/llm/`; MLflow lo referencia por
URI y hash sha256 en `metadata.json` (no se sube como artefacto de MLflow).
