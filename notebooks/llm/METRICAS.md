# Métricas — Generación de título y descripción con LLM local

**Fecha:** 2026-07-14 · **Tarea:** generar `{titulo, descripcion}` de una propiedad a partir del
draft de la API transaccional · **Banco de pruebas:** 7 drafts reales (`drafts_ejemplo.json`)

## Entorno

- **Hardware:** máquina local de desarrollo — 8 cores, 19 GB RAM, inferencia 100% CPU (4 threads).
- **Runtime:** `llama-cpp-python 0.3.34` (llama.cpp), modelos GGUF cuantizados **Q4_K_M**.
- **Contexto configurado:** `n_ctx = 4096` tokens en todas las variantes.

## Preparación previa (una sola vez)

1. **Descarga de modelos** (notebooks 01 y 04): GGUF desde Hugging Face al cache local
   `models_registry/llm/` — `unsloth/Qwen3-4B-Instruct-2507-GGUF` (2.50 GB) y
   `unsloth/Qwen3-1.7B-GGUF` (1.11 GB).
2. **Grafo de conocimiento del dominio** (notebook 03): 33 nodos / 26 aristas curados a mano
   (temas con frases aprobadas, amenidades con aliases, tipos de propiedad, operación
   renta/venta, audiencias). Serializado en `grafo_dominio.json`.
3. **Reglas duras del negocio** en el prompt: nunca precios/montos (el `listedPrice` ni siquiera
   entra al contexto), nunca contacto/urgencia, ubicación solo por nombre de colonia.

## Modelos y modos

| Variante | Modelo | Modo de inferencia |
|---|---|---|
| v2-4B | Qwen3-4B-Instruct-2507 | Prompt directo con el draft (sin grafo). Salida JSON forzada por gramática |
| v3-4B | Qwen3-4B-Instruct-2507 | Draft + contexto curado del grafo (~180 tok). Salida JSON por gramática |
| v3-1.7B | Qwen3-1.7B | Igual que v3, con `/no_think` (desactiva el razonamiento del modelo híbrido). JSON por gramática |
| v3-1.7B-think | Qwen3-1.7B | Igual que v3, con razonamiento `<think>` activo. **Sin gramática** (bloquearía el think); el JSON se parsea de la salida |

**Cómo se hace la inferencia (pipeline v3):** draft JSON → parser (excluye precio, calle e ids)
→ consulta del grafo (amenidades normalizadas por alias → temas → frases aprobadas + audiencia
+ hechos derivados) → system prompt fijo + mensaje con draft y hechos → generación con
`temperature 1.0` (0.6 en modo think) → verificación automática por regex (precio / contacto).

## Métricas (7 inferencias por variante)

| Variante | Tiempo prom. | Rango | Tokens de prompt (contexto acumulado) | Tokens de razonamiento | Palabras salida | RAM | JSON válido | Violaciones precio/contacto |
|---|---|---|---|---|---|---|---|---|
| v2-4B | 21.5 s | 17–31 s | 425 | — | 53 | ~5.0 GB | 7/7 (por gramática) | 0 |
| v3-4B | 26.1 s | 21–36 s | 670 | — | 60 | ~5.0 GB | 7/7 (por gramática) | 0 |
| **v3-1.7B** | **12.9 s** | 12–15 s | 674 | — | 64 | **~2.3 GB** | 7/7 (por gramática) | 0 |
| v3-1.7B-think | 51.0 s | 33–74 s | ~674 | 665 | 49 | ~2.3 GB | 7/7 (parseado) | 0 |

Notas:
- RAM medida sobre el proceso al cargar modelo + contexto (la del 4B se midió en 5.5 GB con
  `n_ctx=8192`; con 4096 se estima ~5.0 GB).
- El system prompt es idéntico entre llamadas y llama.cpp reutiliza ese prefijo, así que el
  costo real por inferencia es procesar solo el draft + grafo (~250–300 tokens nuevos) y generar.
- En modo think el modelo gastó en promedio **665 tokens pensando** para producir ~49 palabras:
  el razonamiento duplica el costo del 4B sin mejorar la garantía de formato.

## Conclusiones

1. **v3-1.7B es el candidato para producción**: 2× más rápido que v3-4B (12.9 s vs 26.1 s),
   menos de la mitad de RAM (2.3 GB vs ~5 GB) y 0 violaciones en las verificaciones automáticas.
   Su calidad de redacción equivale aproximadamente a la del 4B **sin** grafo (v2); el grafo es
   lo que lo hace viable.
2. **El modo think no paga**: 51 s promedio (más lento que el 4B), con la calidad aún por
   debajo de v3-4B y sin gramática que garantice el JSON.
3. **v3-4B queda como referencia de calidad**: si la revisión editorial exige su nivel de
   redacción, el costo es ~2× en tiempo y RAM.
4. Extrapolación al VPS (6 cores, 12 GB, ~1.5–2× más lento): v3-1.7B ≈ **20–26 s por anuncio**
   con ~2.5 GB de RAM — deja al resto del stack (RabbitMQ, MLflow, servicios) espacio de sobra.

**Datos fuente:** `resultados_ab_grafo.csv`, `resultados_qwen17b.csv`,
`resultados_qwen17b_think.csv` (mismos 7 drafts en las 4 variantes).
