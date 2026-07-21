# Propiedades para pruebas del detector de anomalías (Isolation Forest v1)

Guía de valores por tipo de propiedad para construir *drafts* que **pasen** la validación
tabular del modelo `Isolation Forest` (endpoint `POST /analyze`). Solo cubre las features
numéricas y el tipo de propiedad; **no incluye título ni descripción** (esos los evalúa el
análisis de texto por separado).

## Cómo decide el modelo

El modelo empaquetado (`models_registry/anomaly/`, versión `v1`) devuelve un `score`
(`decision_function` del Isolation Forest). La regla de decisión es:

```
is_anomaly = (-score) > score_threshold          # score_threshold = -0.0728
  ⇒  la propiedad es NORMAL (aprobada) solo si  score ≥ +0.0728
```

Cuanto **mayor** sea el `score`, más lejos del umbral y más seguro el aprobado. En este
documento las cajas recomendadas apuntan a `score ≈ 0.10–0.16`, con margen sobrado.

### Features que consumen la decisión

| Campo del `Draft` (JSON) | Feature del modelo | Transformación |
|---|---|---|
| `areaM2` | `areaM2` | `log1p` |
| `listedPrice` | `listedPrice` | `log1p` |
| `pricePerM2` | `pricePerM2` | `log1p` |
| `bedrooms` | `bedrooms` | — |
| `bathrooms` | `bathrooms` | — |
| `parkingSpaces` | `parkingSpaces` | — |
| `constructionYear` | `antiguedad` | `2026 - constructionYear` |
| `condominium` | `condominium` | `0` / `1` |
| `amenityIds` (longitud) | `n_amenities` | `len(amenityIds)` |
| `totalImages` | `total_images` | — |
| `propertyType` | `type_*` | one-hot de 6 columnas |

> **`pricePerM2` debe ser coherente:** `listedPrice ≈ areaM2 × pricePerM2`. Un precio total que
> no cuadre con área × precio/m² es la señal de anomalía más fácil de detectar. Todas las cajas
> de abajo mantienen esa coherencia.

---

## ⚠️ Limitación estructural del modelo v1

El dataset de entrenamiento (`properties_synthetic_v1`) está **muy desbalanceado por tipo**:

| Tipo | Filas normales de entrenamiento | % que aprueba (sobre sus propias filas) |
|---|---:|---:|
| Casa | 4 299 | 98.5 % |
| Departamento | 1 380 | 94.2 % |
| Local Comercial | 276 | 59.4 % |
| **Bodega** | **13** | **0.0 %** |
| **Oficina** | **16** | **0.0 %** |
| **Terreno** | **16** | **0.0 %** |

Por su rareza, el Isolation Forest **aísla** a `Bodega`, `Oficina` y `Terreno` sin importar sus
atributos: incluso las filas marcadas como *normales* en el entrenamiento caen por debajo del
umbral. **Con el modelo v1 es imposible construir una propiedad de estos tres tipos que apruebe**
(el mejor `score` alcanzable sigue por debajo de `0.0728`). Ver la sección
[Tipos que no pasan](#tipos-que-no-pasan-con-v1) al final.

Para pruebas de **aprobación cercana al 100 %**, usa **Casa**, **Departamento** o
**Local Comercial**.

---

## Casa — aprobación ≈ 99.2 %

`propertyType.id = 550e8400-e29b-41d4-a716-446655440001`

| Atributo | Rango recomendado | Variedad sugerida |
|---|---|---|
| `areaM2` | **100 – 560 m²** | 120 · 250 · 380 · 520 |
| `pricePerM2` | **5 000 – 18 000 MXN** | 6 000 · 9 500 · 13 000 · 17 000 |
| `listedPrice` | **= areaM2 × pricePerM2** | (calcular, no inventar) |
| `bedrooms` | **2 – 5** | 2 · 3 · 4 · 5 |
| `bathrooms` | **1.5 – 4** | 1.5 · 2.5 · 3 · 4 |
| `parkingSpaces` | **0 – 4** | 0 · 1 · 2 · 3 |
| `constructionYear` | **1962 – 2018** (antigüedad 8–64) | 1975 · 1990 · 2005 · 2015 |
| `condominium` | `true` o `false` | ambos válidos |
| `amenityIds` (cantidad) | **3 – 14** | 3 · 6 · 9 · 13 |
| `totalImages` | **6 – 24** | 8 · 12 · 18 · 24 |

**Ejemplo válido** (`score ≈ +0.216`): 324 m², precio/m² 11 700, precio 3 790 000, 3 rec, 2 baños,
1 estac., año 2001, sin condominio, 7 amenidades, 13 imágenes.

---

## Departamento — aprobación ≈ 99.2 %

`propertyType.id = 550e8400-e29b-41d4-a716-446655440002`

| Atributo | Rango recomendado | Variedad sugerida |
|---|---|---|
| `areaM2` | **50 – 235 m²** | 55 · 90 · 140 · 220 |
| `pricePerM2` | **7 000 – 36 000 MXN** | 9 000 · 16 000 · 24 000 · 34 000 |
| `listedPrice` | **= areaM2 × pricePerM2** | (calcular) |
| `bedrooms` | **1 – 3** | 1 · 2 · 3 |
| `bathrooms` | **1 – 2.5** | 1 · 1.5 · 2 · 2.5 |
| `parkingSpaces` | **0 – 2** | 0 · 1 · 2 |
| `constructionYear` | **1974 – 2020** (antigüedad 6–52) | 1985 · 2000 · 2012 · 2019 |
| `condominium` | `true` (típico) o `false` | prefiere `true` |
| `amenityIds` (cantidad) | **3 – 14** | 3 · 7 · 10 · 14 |
| `totalImages` | **6 – 24** | 8 · 13 · 18 · 24 |

**Ejemplo válido** (`score ≈ +0.181`): 142 m², precio/m² 19 900, precio 2 830 000, 2 rec,
1.5 baños, 1 estac., año 2011, en condominio, 7 amenidades, 13 imágenes.

---

## Local Comercial — aprobación ≈ 99.6 % (caja estrecha)

`propertyType.id = 550e8400-e29b-41d4-a716-446655440004`

Este tipo tiene margen menor (`score` máximo ≈ 0.138). Manténte **dentro de la caja** y usa
`condominium = false`; salirse de estos rangos baja rápido la tasa de aprobación.

| Atributo | Rango recomendado | Variedad sugerida |
|---|---|---|
| `areaM2` | **130 – 560 m²** | 150 · 260 · 380 · 520 |
| `pricePerM2` | **4 000 – 16 000 MXN** | 5 000 · 8 000 · 11 000 · 15 000 |
| `listedPrice` | **= areaM2 × pricePerM2** | (calcular) |
| `bedrooms` | **0 – 3** | 0 · 1 · 2 · 3 |
| `bathrooms` | **0.5 – 1.5** | 0.5 · 1 · 1.5 |
| `parkingSpaces` | **0 – 2** | 0 · 1 · 2 |
| `constructionYear` | **1972 – 2008** (antigüedad 18–54) | 1980 · 1992 · 2002 · 2008 |
| `condominium` | **`false`** | fija en `false` |
| `amenityIds` (cantidad) | **2 – 13** | 2 · 5 · 9 · 13 |
| `totalImages` | **4 – 22** | 6 · 11 · 16 · 22 |

**Ejemplo válido** (`score ≈ +0.127`): 294 m², precio/m² 8 900, precio 2 617 000, 1 rec, 1 baño,
1 estac., año 2006, sin condominio, 7 amenidades, 13 imágenes.

---

## Tipos que NO pasan con v1

Para `Bodega`, `Oficina` y `Terreno` **ninguna combinación aprueba** con el modelo actual (score
máximo alcanzable por debajo del umbral `0.0728`). Estos son los mejores casos encontrados por
búsqueda exhaustiva, útiles solo para documentar el límite:

| Tipo | `id` | Mejor `score` (umbral 0.0728) | Config del mejor caso |
|---|---|---:|---|
| Oficina | `…440005` | **+0.029** ❌ | 186 m², $/m² 7 355, 1 rec, 1 baño, 1 estac., año 1998, 8 amen., 14 img |
| Terreno | `…440003` | **+0.016** ❌ | 273 m², $/m² 4 233, 0 rec, 0 baños, 0 estac., año 1992, 4 amen., 14 img |
| Bodega | `…440006` | **+0.011** ❌ | 466 m², $/m² 13 269, 0 rec, 1 baño, 2 estac., año 1981, 4 amen., 13 img |

### Cómo habilitarlos (fuera del alcance de esta tabla)

Requiere reentrenar el modelo, no ajustar los datos de prueba. Opciones:

1. **Rebalancear el dataset** — generar cientos de filas sintéticas de `Bodega`, `Oficina` y
   `Terreno` (equiparar a `Local Comercial` o más) y reentrenar.
2. **Subir `contamination`** o ajustar `score_threshold` (empeora el poder discriminante global).
3. **Modelo por tipo** — un Isolation Forest independiente por `propertyType`.

---

## Notas de uso

- El campo real que cuenta amenidades es la **longitud de `amenityIds`**; el contenido de los IDs
  no afecta al modelo tabular.
- `totalImages` es una feature: valores muy bajos (0–2) restan `score`. Usa ≥ 6 para margen.
- Todos los porcentajes de aprobación se midieron muestreando 60 000 propiedades por tipo dentro
  de cada caja recomendada y evaluándolas contra el artefacto `isolation_forest_v1.joblib`.
