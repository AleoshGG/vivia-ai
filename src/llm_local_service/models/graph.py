"""Estructuras de datos del grafo ponderado de conocimiento (v4).

Solo dataclasses: la carga/validación vive en `services/graph_loader.py`, la
inferencia en `services/graph_inference.py` y la construcción del mensaje al
LLM en `services/summary_builder.py`. Los identificadores están en inglés;
los textos (frases, tonos, narrativas) siguen en español porque son contenido
del prompt, no código.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Edge:
    """Arista ponderada del grafo."""

    origin: str
    target: str
    weight: float
    relation: str  # evoca | prior | sugiere | bloquea
    reason: str = ""


@dataclass
class Domain:
    """Dominio completo cargado desde los CSVs de `resources/graph/`."""

    amenities: dict[str, dict]        # clave -> {db_name, aliases}
    themes: dict[str, dict]           # clave -> {frase_1, frase_2}
    property_types: dict[str, str]    # nombre BD -> narrativa
    operations: dict[str, str]        # RENTA/VENTA -> tono
    audiences: dict[str, str]         # clave -> frase
    buckets: dict[str, str]           # clave -> condición (documental)
    edges: list[Edge]
    # Índice alias normalizado -> clave de amenidad; lo construye el loader.
    alias_to_amenity: dict[str, str] = field(default_factory=dict)
    _by_origin: dict[str, list[Edge]] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for edge in self.edges:
            self._by_origin.setdefault(edge.origin, []).append(edge)

    def edges_from(self, origin: str) -> list[Edge]:
        return self._by_origin.get(origin, [])


@dataclass
class Decision:
    """Decisión editorial producida por la inferencia sobre el grafo."""

    draft_id: str
    activations: list[str]
    unknown_amenities: list[str]
    scores: dict[str, float]              # tema -> score acumulado
    blocked: dict[str, list[Edge]]        # tema -> bloqueos aplicados
    themes: list[str]                     # ganadores, en orden
    audience: str | None
    main_amenities: list[str]             # nombres BD de amenidades a destacar
    secondary_amenities: list[str]
    facts: list[str]
    trace: list[str]                      # bitácora legible de la propagación
