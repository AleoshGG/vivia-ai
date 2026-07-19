# Plan: Detección de fraude en título y descripción (análisis de texto)

## Objetivo

Ampliar la detección de anomalías para que, además del vector tabular
(Isolation Forest), analice el **título** y la **descripción** del `Draft` y
detecte redacción fraudulenta: filtración de contacto fuera de plataforma
(teléfonos, WhatsApp, correos, URLs), presión/urgencia comercial
("compra ya", "de inmediato", "última oportunidad") y solicitud de pago
directo ("a 500 pesos"). El veredicto de texto se **fusiona** con el del
Isolation Forest para producir la decisión final de aprobación.

## Alcance

**Incluido**
- Subsistema de riesgo textual desacoplado dentro de `anomaly_detector_api`
  (frontera SOLID propia: `services/text_risk/`).
- **Capa 0 — Reglas deterministas** (regex/léxico): teléfonos MX, correos,
  URLs, WhatsApp, urgencia y precio. Alta precisión, ~0 ms.
- **Capa 1 — Zero-shot con LLM local**: cliente **no-streaming, salida JSON
  restringida** contra el `llama-server` (Qwen3) ya existente, que actúa como
  *Information Extractor + Fraud Intent Detector* combinados.
- **Fusión (Decision Engine)**: combina reglas + LLM + score del Isolation
  Forest en `AnalyzePropertyUseCase`. Las reglas duras (contacto directo) son
  bloqueo directo; el LLM aporta score + razones.
- Persistencia del veredicto textual (score, etiqueta, razones, entidades
  extraídas) junto a la inferencia.
- Reutilización de los patrones ya validados `RE_PRECIO` / `RE_CONTACTO`
  (hoy en `llm_local_service` y en notebooks).

**Excluido (límites claros)**
- **Sin entrenamiento supervisado** en esta fase: no hay datos etiquetados, se
  arranca en frío con reglas + zero-shot. (Fase futura: recolectar veredictos
  → dataset → clasificador ligero BETO/LightGBM.)
- **Sin embeddings ni modelos transformer nuevos** cargados en el servicio: el
  cómputo de texto reusa el `llama-server`, no se añaden dependencias de
  `sentence-transformers` ni `torch`.
- **Sin verificación de consistencia texto↔formulario (NLI)** todavía: es la
  Capa 2, diferida a un plan posterior.
- No se reentrena el Isolation Forest ni se tocan sus features tabulares
  (fusión **tardía**, no temprana).
- No se modifica el path de streaming del móvil (`llm_local_service`).

## Cambios por capa

### `models/` (`anomaly_detector_api`)
- `models/text_risk.py` (nuevo): modelos Pydantic
  - `RuleSignals`: `phones`, `emails`, `urls`, `price_hits`, `cta_hits`, `has_hard_contact` (bool).
  - `LlmVerdict`: `risk_score` (0.0–1.0), `label` (`limpio`|`sospechoso`|`fraude`), `reasons: list[str]`, `extracted: dict`.
  - `TextRiskResult`: veredicto fusionado del subsistema → `risk_score`, `label`, `is_fraud_text` (bool), `reasons: list[str]`, `source` (`rules`|`llm`|`both`).

### `services/text_risk/` (nuevo subsistema)
- `rules.py` — **Capa 0**. Función pura `evaluate_rules(title, description) -> RuleSignals`.
  Regex de teléfono MX (10 dígitos con separadores/lada), correo, URL/dominio,
  más `RE_PRECIO`/`RE_CONTACTO` reutilizados. `has_hard_contact` = hay teléfono,
  correo o URL explícito.
- `prompt.py` — system prompt del clasificador de fraude (Español MX), pide un
  **JSON estricto** con `{risk_score, label, reasons, extracted}`. Versionado
  (`TEXT_RISK_PROMPT_VERSION`).
- `llm_text_client.py` — **Capa 1**. `LlamaTextRiskClient` con
  `async classify(title, description) -> LlmVerdict`. Reusa el patrón de
  `LlamaServerHttpClient` pero **no-streaming** y con
  `response_format={"type":"json_object"}` (+ `enable_thinking: False`,
  `temperature` baja). Ante `LlamaServerUnavailable` degrada a `None` (solo
  reglas) sin abortar el análisis.
- `text_risk_service.py` — **Decision Engine textual**.
  `async evaluate(title, description) -> TextRiskResult`: corre reglas; si
  `has_hard_contact` marca `is_fraud_text=True` (bloqueo duro) y **puede saltar**
  la llamada al LLM; si no, invoca la Capa 1 y fusiona (umbral configurable
  sobre `risk_score`). Devuelve razones legibles para el campo `reason`.

### `usecases/analyze_property.py` (fusión)
- Inyectar `TextRiskService` en el `__init__`.
- En `execute`: correr `text_risk.evaluate(draft.title, draft.description)` en
  paralelo con la predicción tabular.
- Decisión final: `approved = (not is_anomaly) and (not text.is_fraud_text)`.
- `reason` enriquecido: si el rechazo viene del texto, explicitar la causa
  (p. ej. *"Rechazada: la descripción incluye un número de contacto directo."*).
- Persistir el veredicto textual junto a la inferencia.

### `persistence/` + `alembic`
- Extender `AnomalyInference` (`models_db.py`) con columnas:
  `text_risk_score` (float, nullable), `text_label` (str, nullable),
  `text_reasons` (JSONB, nullable).
- Nueva migración Alembic para esas columnas.
- Extender `InferenceRepository.save(...)` y los modelos de salida
  (`InferenceRecord`) para exponerlas.

### `config/`
- Nuevos settings: `LLAMA_SERVER_URL` (para el worker de anomalías),
  `text_risk_llm_enabled` (bool), `text_risk_threshold` (float),
  `text_risk_timeout_s`. Feature-flag para poder operar **solo con reglas** si
  el `llama-server` no está disponible.

### `main.py`
- Construir `LlamaTextRiskClient` y `TextRiskService` al startup y colgarlos en
  `app.state` para inyectarlos en el use case (mismo patrón que
  `anomaly_model` / `inference_repository`).

## Dependencias

- **`llama-server` (`vivia-llama-server`)**: el contenedor de
  `anomaly_detector_api` (API y worker) debe alcanzarlo por red y tener
  `LLAMA_SERVER_URL`. Ver `compose.yml`.
- **Contención de recurso**: `llama-server` corre `--parallel 1`; las
  peticiones de anomalías y las de generación en vivo **se serializan** en el
  mismo slot. Aceptable porque la detección de anomalías es trabajo de fondo
  (worker de cola), no path de streaming. Mitigación: reglas primero y saltar el
  LLM en bloqueos duros; feature-flag para desactivar la Capa 1.
- Reutiliza `RE_PRECIO` / `RE_CONTACTO` (patrón ya validado en notebooks y
  `llm_local_service`). No se borran los originales; se consolida una copia en
  `services/text_risk/rules.py`.
- Toca el contrato de `analyze_property` / `detect` (worker de cola
  `anomaly_queue_consumer`), ambos consumidores del `AnalyzePropertyUseCase`.

## Pasos de implementación

1. `models/text_risk.py`: `RuleSignals`, `LlmVerdict`, `TextRiskResult`.
2. `services/text_risk/rules.py`: `evaluate_rules` con regex de teléfono/correo/
   URL + reuso de `RE_PRECIO`/`RE_CONTACTO`.
3. `services/text_risk/prompt.py`: system prompt versionado del clasificador
   zero-shot con esquema JSON de salida.
4. `services/text_risk/llm_text_client.py`: `LlamaTextRiskClient.classify`
   (no-streaming, JSON, degradación ante `LlamaServerUnavailable`).
5. `services/text_risk/text_risk_service.py`: orquestación reglas → LLM →
   fusión → `TextRiskResult` (con bloqueo duro y umbral).
6. `config/`: settings y feature-flags nuevos.
7. `main.py`: instanciar cliente + servicio en el startup y exponer en
   `app.state`.
8. `usecases/analyze_property.py`: inyectar `TextRiskService`, evaluar en
   paralelo, fusionar decisión y enriquecer `reason`.
9. Persistencia: columnas nuevas en `AnomalyInference`, migración Alembic,
   `InferenceRepository.save` y `InferenceRecord`.
10. `compose.yml` / `.env.example`: `LLAMA_SERVER_URL` y flags para el servicio
    de anomalías.
