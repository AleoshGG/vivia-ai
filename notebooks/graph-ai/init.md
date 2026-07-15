# Grafo de inferencia ponderado — concepto y metodología

> Línea de experimentación `notebooks/graph-ai/`. Evolución del grafo de conocimiento del
> notebook 03 (`notebooks/llm/grafo_dominio.json`): de un grafo que *recupera* contexto a un
> grafo que *decide* antes del LLM.

## 1. Contexto y motivación

Los experimentos previos (`notebooks/llm/`, ver `METRICAS.md`) dejaron esta situación:

| Variante | Tiempo/anuncio | Calidad |
|---|---|---|
| v3-4B (grafo como contexto) | ~26 s | La referencia |
| v3-1.7B (grafo como contexto) | ~13 s | ≈ 4B sin grafo; clichés ocasionales |

El grafo v3 es una **biblioteca**: recupera todos los ángulos activados (~184 tokens) y el LLM
decide cuáles usar y cómo dosificarlos. Esa decisión es justo lo que un modelo de 1.7B hace
peor (de ahí los clichés tipo "oportunidad única") y lo que hace al prompt largo.

**Hipótesis del grafo ponderado (v4):** si el grafo toma las decisiones editoriales
(narrativa, tono, audiencia, temas, amenidades prioritarias) y al LLM solo le llega un resumen
prescriptivo (~70 tokens), entonces:

1. El prompt baja de ~700 a ~520 tokens (−2 a −4 s por anuncio).
2. **La ganancia grande:** el 1.7B alcanza la calidad del 4B, porque le quitamos lo que hace
   mal (decidir) y le dejamos lo que hace bien (redactar 21–70 palabras fluidas).
   Objetivo: calidad v3-4B a ~11 s por anuncio.
3. Las decisiones se vuelven deterministas, testeables y auditables.

Nota de expectativas: la consulta del grafo ya tarda ~0.04 ms (medido en
`benchmark_grafo_4b.py`) — "compilar" el grafo no acelera el runtime de forma medible. El valor
está en menos tokens y en el control editorial, no en la velocidad de la consulta.

## 2. El concepto: el grafo como enrutador

Analogía de la ciudad: en un grafo vial, los pesos de las calles deciden la ruta del vehículo y
las calles en sentido contrario tienen peso prohibitivo — bloquean el paso del algoritmo.
Trasladado al dominio:

- **El draft activa nodos fuente** (las amenidades presentes, el tipo, la operación, los
  atributos derivados) — los puntos de partida.
- **Los pesos de las aristas hacen competir a los temas** — las avenidas por donde puede fluir
  la narrativa. `score(tema) = Σ activación(fuente) × peso(arista)`.
- **Las reglas de negocio son bloqueos** (peso −10, efectivamente −∞): `VENTA ⊣ flexibilidad`,
  `antigüedad>30 ⊣ estilo_moderno`. Un tema bloqueado no puede ganar aunque tres amenidades lo
  empujen — la calle en sentido contrario no se toma por muy corta que sea la ruta.
- **La selección top-k es la ruta elegida**, y queda una traza de por qué (qué aristas sumaron
  cuánto) — auditable por el negocio.

### Flujo completo

```
draft JSON ──> activaciones ──> propagación ponderada ──> selección ──> resumen compacto ──> LLM
              (nodos fuente)     (1 salto, pesos,          (top-k,       (~70 tokens,         (solo
               discretizados)     bloqueos)                 desempates)   prescriptivo)        redacta)
```

Salida del grafo (lo único que ve el LLM además del draft):

```
DECISIONES DE REDACCIÓN (obligatorias):
- Narrativa: casa — espacios, independencia, vida cotidiana
- Tono: renta, facilidad de instalarse
- Audiencia: familias que necesitan espacio para todos
- Temas (en este orden): vida al aire libre; bienestar
- Amenidades protagonistas: terraza, gimnasio. Secundaria: jardín
- Hechos: a estrenar; superficie amplia
```

## 3. Ontología (el plano de la ciudad)

Vocabulario cerrado de nodos y relaciones. Todo nodo fuente debe ser derivable del draft real
de la API transaccional — el grafo no puede requerir información que el draft no trae.

| Capa | Nodos | Ejemplos |
|---|---|---|
| **Fuente** | amenidades canónicas, tipo de propiedad, operación, *buckets* de atributos | `gimnasio`, `CASA`, `RENTA`, `rec≥4`, `a_estrenar`, `area≥180` |
| **Intermedia** | temas (8–12; más no acumulan peso diferenciable en un anuncio de 21–70 palabras) | `vida_al_aire_libre`, `bienestar`, `practicidad` |
| **Decisión** | audiencia, narrativa, tono | `familia_grande`, narrativa de casa, tono de renta |

| Relación | De → a | Peso |
|---|---|---|
| `evoca` | amenidad → tema | 0.3 / 0.6 / 0.9 |
| `prior` | tipo u operación → tema | máx 0.8 (nunca debe ganarle a dos amenidades reales) |
| `sugiere` | bucket de atributo → audiencia | 0.3 / 0.6 / 0.9 |
| `bloquea` | regla de negocio → tema | −10 (binario, no gradual; siempre con su porqué documentado) |

Cada tipo de relación nuevo debe justificar su existencia o el grafo se vuelve inmantenible.

## 4. Metodología de construcción

1. **Fijar la ontología** (arriba) antes de asignar un solo peso.
2. **Discretizar el draft**: los campos continuos entran como buckets con umbral explícito y
   documentado (`bedrooms≥4`, `antigüedad≤1 → a_estrenar`, `areaM2≥180 → amplia`). Cada umbral
   es una decisión de negocio; los percentiles del corpus Properati pueden dar sustento local.
   Las amenidades pasan por la tabla de aliases (`GYM → gimnasio`).
3. **Definir el catálogo de temas**: un tema existe si es (a) distinguible — si dos temas
   siempre ganan juntos, son uno; (b) redactable en 21–70 palabras; (c) tiene 2–3 frases
   semilla aprobadas por negocio.
4. **Elicitar pesos por niveles discretos**, no números continuos. La matriz amenidad×tema se
   llena celda por celda con una sola pregunta: *"si la propiedad tiene X, ¿qué tanto justifica
   hablar de Y?"* → fuerte (0.9) / medio (0.6) / débil (0.3) / sin arista. Con el dominio
   actual (14 amenidades × 9 temas + priors + audiencias) son ~130 celdas, ~40 con arista:
   una tarde de trabajo con alguien de negocio.
5. **Definir propagación y selección**: suma ponderada a 1 salto; bloqueo mata al tema;
   decisiones explícitas de **k** (=2 temas para este formato), **desempate** (gana el tema
   cuya amenidad contribuyente tenga mayor peso — la decisión siempre es trazable a algo físico
   de la propiedad) y **umbral mínimo** (si ningún tema pasa de 0.5 — draft sin amenidades —
   el resumen sale con narrativa + hechos, sin forzar un tema débil).
6. **Validar como código, no con vibras**:
   - *Tests de decisión*: "draft-001 (terraza+jardín+GYM, casa, renta) → temas = [vida al aire
     libre, bienestar], audiencia = familia_grande". Los 7 drafts de `drafts_ejemplo.json` son
     la suite inicial.
   - *Tests de bloqueo*: "ningún draft de VENTA produce jamás flexibilidad" — verificación
     exhaustiva, no probabilística.
   - *Traza obligatoria*: toda decisión loguea su ruta (qué aristas sumaron cuánto).
   - Después, A/B con lectura manual: v3-4B (baseline) vs v4-4B vs v4-1.7B.
7. **Gobernanza**: el grafo es un artefacto versionado (JSON; candidato a MLflow como en el
   plan). Cambiar un peso es un release con tests. Las amenidades desconocidas se loguean en
   producción y son el backlog de la siguiente versión (¿alias o canónica nueva? ¿qué evoca y
   con qué nivel?).

## 5. Insumos requeridos

1. **Esquema del draft** — ya se tiene (define los nodos fuente posibles).
2. **Inventario real del dominio** — catálogo de amenidades/tipos de la BD transaccional
   (si la captura es de lista cerrada, esa lista es el censo; si es texto libre, aliases).
3. **Línea editorial del negocio** — temas permitidos, frases aprobadas, prohibiciones
   (vigentes: nunca precio/montos, nunca contacto/urgencia, ubicación solo por colonia).
4. **Evidencia para pesos** — juicio experto para arrancar; co-ocurrencias del corpus y
   retroalimentación de anuncios generados para calibrar.

## 6. Reglas duras heredadas (invariantes)

Independientes del grafo, se mantienen del pipeline v3:

- `listedPrice` **no entra** al contexto del modelo (lo que no ve, no lo menciona).
- Sin lenguaje de contacto, urgencia ni llamados a la acción.
- Ubicación = solo `neighborhoodName`; sin calle/números ni atributos de zona.
- Salida JSON `{titulo, descripcion}` forzada por gramática; verificación regex post-generación.

## 7. Criterios de éxito del experimento

| Métrica | v3-4B (baseline) | Objetivo v4-1.7B |
|---|---|---|
| Tokens de prompt | ~700 | ~520 |
| Tiempo por anuncio (local, 4 threads) | ~26 s | ~11 s |
| Violaciones precio/contacto | 0/7 | 0/7 |
| Tests de decisión y bloqueo | n/a (decide el LLM) | 100% verdes |
| Calidad (lectura manual lado a lado) | referencia | indistinguible del baseline |

## Artefactos relacionados

- `notebooks/llm/grafo_dominio.json` — grafo v3 (sin pesos), punto de partida.
- `notebooks/llm/drafts_ejemplo.json` — 7 drafts con el esquema real de la API.
- `notebooks/llm/METRICAS.md` — métricas de las 4 variantes previas.
- `notebooks/llm/benchmark_grafo_4b.py` — benchmark por etapas del pipeline v3.
- `docs/PLANS/2026-07-14-PLAN_LLM_GENERACION_TITULO_DESCRIPCION_.md` — plan general.
