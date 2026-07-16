# Plan: Prompt v5 — redacción cualitativa (sin cifras crudas) para Qwen3 1.7B no-thinking

## Contexto

El experimento en [notebooks/graph-ai/prompt.py](notebooks/graph-ai/prompt.py) ya corre con Qwen3-1.7B en modo no-thinking a buena velocidad (~10-14 tokens/s). El problema es la calidad: el modelo transcribe los datos del draft tal cual ("4 recámaras, 3 baños y 2 estacionamientos", "A estrenar en 2025", "Gimnasio de pasada") en vez de redactar prosa cálida y fluida.

Causas identificadas:

1. `draft_json_a_texto()` ([motor_inferencia.py:312](notebooks/graph-ai/motor_inferencia.py#L312)) presenta el draft como ficha técnica ("Recámaras: 4", "Baños: 3") y el system prompt actual (`SYSTEM_PROMPT_V4`) no prohíbe transcribir esas cifras — de hecho la regla 1 ("escribe SOLO con la información del DRAFT") empuja al modelo a copiarlas.
2. El resumen del grafo usa lenguaje meta ("Secundarias (solo de pasada): Gimnasio") que el modelo copia literal ("El gimnasio está disponible de pasada" / "Gimnasio de pasada").
3. El título no tiene formato definido, por eso salen títulos secos como "Casa Prudencio Moscoso" en vez de "Casa en Prudencio Moscoso para renta".

## Objetivo

Que el anuncio se lea como redacción humana: cifras traducidas a lenguaje cualitativo, temas del grafo desarrollados como narrativa, y título con formato consistente. Ejemplo objetivo del usuario:

> **Título:** Casa en Prudencio Moscoso para renta
> **Descripción:** Una casa amplia de 200 m² en Prudencio Moscoso, a estrenar, donde el aire libre es una constante. Espacios para disfrutar el aire libre sin salir de casa, con terraza y jardín que invitan a relajarse y compartir momentos. Pensada para la convivencia en familia, con recámaras para cada miembro y un ambiente que fomenta la tranquilidad diaria.

## Alcance

- **Incluido:** solo el system prompt (`SYSTEM_PROMPT_V4` → `SYSTEM_PROMPT_V5`) en [prompt.py](notebooks/graph-ai/prompt.py). Es un experimento de prompt engineering iterativo; el motor del grafo no se toca.
- **Excluido:** cambios a `motor_inferencia.py` (formato del draft/resumen), al servidor, al modelo o a las métricas.

## Cambios

### 1. Reescribir el system prompt (v5) en prompt.py

Reglas nuevas/reforzadas:

- **Prohibido escribir cifras del draft**: número de recámaras, baños, estacionamientos y año de construcción nunca aparecen como número. La única cifra permitida es la superficie en m². Traducir cantidades a lenguaje cualitativo: "recámaras para cada miembro de la familia", "baños suficientes para la rutina diaria", "espacio para tus autos", "a estrenar" (sin año).
- **Prohibido el estilo ficha técnica**: no enumerar características en lista ("con X, Y y Z"); desarrollar los temas del grafo como narrativa fluida.
- **Prohibido copiar lenguaje meta de las DECISIONES**: palabras como "protagonistas", "secundarias", "de pasada", "temas", "audiencia" jamás aparecen en el anuncio. Las amenidades secundarias se integran con naturalidad en una frase, sin señalar que son secundarias.
- **Formato de título fijo**: "<Tipo de propiedad> en <Colonia> para <renta|venta>" (máx. 10 palabras).
- Mantener: JSON con "titulo" y "descripcion", 21–70 palabras, sin precios/contacto/urgencia, vocabulario regional.

### 2. Agregar un ejemplo one-shot dentro del system prompt

Los modelos de 1.7B siguen ejemplos mucho mejor que reglas abstractas. Incluir un mini ejemplo entrada→salida usando exactamente el resultado objetivo del usuario (draft-001), mostrando cómo "Recámaras: 4" se convierte en "recámaras para cada miembro" y cómo el gimnasio secundario se menciona sin decir "de pasada".

Costo: ~150-200 tokens extra de entrada (solo prefill; no afecta la velocidad de generación, que es lo que importa). Entrada actual ~590 tokens → ~790.

### 3. Actualizar referencias v4 → v5

Renombrar la constante y su uso en `generar_para_draft()`, y el encabezado "Decisiones del Grafo (v4)" queda igual (es del grafo, no del prompt).

### 4. Documentar el plan en el repo

Crear `docs/PLANS/2026-07-15-PLAN_PROMPT_V5_QWEN3_17B_.md` con este contenido (requisito del CLAUDE.md del proyecto).

## Verificación

1. Ejecutar `python prompt.py` desde `notebooks/graph-ai/`.
2. Revisar `results.md`: en las 3 inferencias no debe aparecer ningún número de recámaras/baños/estacionamientos ni año; solo m². No deben aparecer "de pasada", "secundaria", "protagonista".
3. Títulos con formato "<Tipo> en <Colonia> para <renta|venta>".
4. Comparar velocidad (tokens/s) contra la corrida anterior (~10-14 tokens/s) para confirmar que el one-shot no la degrada.
5. Si el modelo sigue colando cifras, iterar: subir la prohibición al inicio del prompt y/o repetirla al final (los modelos chicos pesan más los extremos del prompt).
