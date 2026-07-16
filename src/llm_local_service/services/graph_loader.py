"""Carga y validación del dominio del grafo desde los CSVs de `resources/graph/`.

Única responsabilidad: leer los 10 CSVs, validar claves y escalas, y construir
el `Domain`. Falla temprano (ValueError) si algo no cuadra — mejor al arranque
del servicio que a mitad de una inferencia.
"""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path

from ..models.graph import Domain, Edge

BLOCK_WEIGHT = -10.0
VALID_WEIGHTS = {0.3, 0.6, 0.9}
MAX_PRIOR = 0.8


def normalize(text: str) -> str:
    """Minúsculas, sin acentos ni espacios extremos — para comparar claves/aliases."""
    text = unicodedata.normalize("NFKD", str(text).lower().strip())
    return "".join(c for c in text if not unicodedata.combining(c))


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_domain(datasets_path: Path | str) -> Domain:
    """Lee los CSVs del grafo y valida claves y escalas."""
    ds = Path(datasets_path)
    amenities = {r["amenidad"]: {"db_name": r["nombre_db"],
                                 "aliases": [a for a in r["aliases"].split("|") if a]}
                 for r in _read_csv(ds / "amenidades.csv")}
    themes = {r["tema"]: {"frase_1": r["frase_1"], "frase_2": r["frase_2"]}
              for r in _read_csv(ds / "temas.csv")}
    property_types = {r["tipo"]: r["narrativa"] for r in _read_csv(ds / "tipos_propiedad.csv")}
    operations = {r["operacion"]: r["tono"] for r in _read_csv(ds / "operaciones.csv")}
    audiences = {r["audiencia"]: r["frase"] for r in _read_csv(ds / "audiencias.csv")}
    buckets = {r["bucket"]: r["condicion"] for r in _read_csv(ds / "buckets.csv")}

    sources = set(buckets) | set(property_types) | set(operations)
    errors: list[str] = []
    edges: list[Edge] = []

    for r in _read_csv(ds / "pesos_evoca.csv"):
        amenity = r.pop("amenidad")
        if amenity not in amenities:
            errors.append(f"pesos_evoca: amenidad desconocida '{amenity}'")
            continue
        for theme, cell in r.items():
            if not cell:
                continue
            weight = float(cell)
            if theme not in themes:
                errors.append(f"pesos_evoca: tema desconocido '{theme}'")
            elif weight not in VALID_WEIGHTS:
                errors.append(f"pesos_evoca: peso fuera de escala {weight} en {amenity}→{theme}")
            else:
                edges.append(Edge(f"am:{amenity}", theme, weight, "evoca"))

    for r in _read_csv(ds / "pesos_priors.csv"):
        weight = float(r["peso"])
        if r["origen"] not in sources:
            errors.append(f"pesos_priors: origen desconocido '{r['origen']}'")
        elif r["tema"] not in themes:
            errors.append(f"pesos_priors: tema desconocido '{r['tema']}'")
        elif weight > MAX_PRIOR:
            errors.append(f"pesos_priors: prior {weight} > {MAX_PRIOR} en {r['origen']}→{r['tema']}")
        else:
            edges.append(Edge(f"src:{r['origen']}", r["tema"], weight, "prior"))

    for r in _read_csv(ds / "reglas_audiencia.csv"):
        if r["origen"] not in sources:
            errors.append(f"reglas_audiencia: origen desconocido '{r['origen']}'")
        elif r["audiencia"] not in audiences:
            errors.append(f"reglas_audiencia: audiencia desconocida '{r['audiencia']}'")
        else:
            edges.append(Edge(f"src:{r['origen']}", f"aud:{r['audiencia']}",
                              float(r["peso"]), "sugiere"))

    for r in _read_csv(ds / "bloqueos.csv"):
        if r["origen"] not in sources:
            errors.append(f"bloqueos: origen desconocido '{r['origen']}'")
        elif r["tema_bloqueado"] not in themes:
            errors.append(f"bloqueos: tema desconocido '{r['tema_bloqueado']}'")
        else:
            edges.append(Edge(f"src:{r['origen']}", r["tema_bloqueado"],
                              BLOCK_WEIGHT, "bloquea", r["porque"]))

    if errors:
        raise ValueError("Dominio inválido:\n- " + "\n- ".join(errors))

    alias_to_amenity = {
        normalize(alias): key
        for key, data in amenities.items()
        for alias in data["aliases"] + [data["db_name"]]
        if alias
    }
    return Domain(amenities, themes, property_types, operations, audiences,
                  buckets, edges, alias_to_amenity)
