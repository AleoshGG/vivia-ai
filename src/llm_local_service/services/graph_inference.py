"""Inferencia sobre el grafo ponderado (v4).

Única responsabilidad: dado un draft (dict camelCase de la API transaccional),
activar nodos fuente, propagar pesos hacia temas y audiencias, aplicar bloqueos
(peso −10) y producir la `Decision` editorial. Misma semántica validada en
`notebooks/graph-ai/motor_inferencia.py`: k=2 temas, umbral 0.5, desempate por
la arista contribuyente de mayor peso.
"""

from __future__ import annotations

from datetime import date

from ..models.graph import Decision, Domain, Edge
from .graph_loader import normalize

# Textos aprobados para los hechos derivados de buckets (espejo de buckets.csv).
BUCKET_FACTS = {
    "a_estrenar": "a estrenar",
    "construccion_reciente": "construcción reciente",
    "con_historia": "más de 30 años: nombrarla como carácter e historia, sin afirmar estado",
    "area_amplia": "superficie amplia",
    "area_compacta": "espacio compacto y eficiente (no describir como amplio)",
    "en_condominio": "forma parte de un condominio",
    "sin_estacionamiento": "no mencionar estacionamientos",
}


def buckets_for(draft: dict, current_year: int | None = None) -> list[str]:
    """Discretiza el draft (espejo de las condiciones documentadas en buckets.csv)."""
    year = current_year or date.today().year
    age = year - draft["constructionYear"]
    b = []
    if age <= 1:
        b.append("a_estrenar")
    elif age <= 10:
        b.append("construccion_reciente")
    if age > 30:
        b.append("con_historia")
    if draft["areaM2"] >= 180:
        b.append("area_amplia")
    if draft["areaM2"] <= 50:
        b.append("area_compacta")
    if draft["bedrooms"] >= 4:
        b.append("rec_4_mas")
    elif draft["bedrooms"] >= 2:
        b.append("rec_2_3")
    elif draft["bedrooms"] == 1:
        b.append("rec_1")
    if draft["condominium"]:
        b.append("en_condominio")
    if draft["parkingSpaces"] == 0:
        b.append("sin_estacionamiento")
    return b


class GraphInferenceService:
    """Motor de inferencia: se construye una vez con el dominio ya cargado."""

    def __init__(self, domain: Domain):
        self._domain = domain

    @property
    def domain(self) -> Domain:
        return self._domain

    def _activate(self, draft: dict, current_year: int | None = None):
        """Nodos fuente activados por el draft + amenidades sin resolver."""
        domain = self._domain
        operation = "RENTA" if draft["availableToRent"] else "VENTA"
        active = [f"src:{operation}"]
        prop_type = next(
            (t for t in domain.property_types
             if normalize(t) == normalize(draft["propertyType"]["name"])),
            None,
        )
        if prop_type:
            active.append(f"src:{prop_type}")
        active += [f"src:{b}" for b in buckets_for(draft, current_year)]
        unknown = []
        for amenity in draft.get("amenities", []):
            key = domain.alias_to_amenity.get(normalize(amenity))
            if key:
                active.append(f"am:{key}")
            else:
                unknown.append(amenity)
        return active, unknown, operation, prop_type

    def infer(self, draft: dict, k: int = 2, threshold: float = 0.5,
              current_year: int | None = None) -> Decision:
        domain = self._domain
        active, unknown, _operation, _prop_type = self._activate(draft, current_year)

        scores: dict[str, float] = {}
        contributions: dict[str, list[Edge]] = {}
        blocked: dict[str, list[Edge]] = {}
        trace: list[str] = [f"activaciones: {', '.join(a.split(':', 1)[1] for a in active)}"]

        for origin in active:
            for edge in domain.edges_from(origin):
                scores[edge.target] = scores.get(edge.target, 0.0) + edge.weight
                contributions.setdefault(edge.target, []).append(edge)
                if edge.relation == "bloquea":
                    blocked.setdefault(edge.target, []).append(edge)
                    trace.append(
                        f"BLOQUEO {edge.target} ⊣ {origin.split(':', 1)[1]}: {edge.reason}"
                    )
                else:
                    trace.append(f"{origin.split(':', 1)[1]} → {edge.target} (+{edge.weight})")

        def max_contribution(target: str) -> float:
            return max(
                (e.weight for e in contributions.get(target, []) if e.relation != "bloquea"),
                default=0.0,
            )

        # Temas: score desc, desempate por arista contribuyente máxima; bloqueado descalifica.
        ranking = sorted(domain.themes, key=lambda t: (-scores.get(t, 0.0), -max_contribution(t)))
        winners = [t for t in ranking if t not in blocked and scores.get(t, 0.0) >= threshold][:k]
        trace.append(f"temas ganadores (k={k}, umbral={threshold}): {winners}")

        # Audiencia: top-1 con score > 0; desempate por contribución máxima y orden del catálogo.
        audience_order = list(domain.audiences)
        audience_rank = sorted(
            audience_order,
            key=lambda a: (-scores.get(f"aud:{a}", 0.0),
                           -max_contribution(f"aud:{a}"), audience_order.index(a)),
        )
        audience = (audience_rank[0]
                    if scores.get(f"aud:{audience_rank[0]}", 0.0) > 0 else None)
        trace.append(f"audiencia: {audience}")

        # Amenidades protagonistas: las que más contribuyen a los temas ganadores.
        contributors: dict[str, float] = {}
        for theme in winners:
            for edge in contributions.get(theme, []):
                if edge.relation == "evoca":
                    key = edge.origin.split(":", 1)[1]
                    contributors[key] = max(contributors.get(key, 0.0), edge.weight)
        main = sorted(contributors, key=lambda c: -contributors[c])[:2]
        known = [domain.alias_to_amenity[normalize(x)] for x in draft.get("amenities", [])
                 if normalize(x) in domain.alias_to_amenity]
        secondary = [c for c in known if c not in main]

        facts = [BUCKET_FACTS[b] for b in buckets_for(draft, current_year) if b in BUCKET_FACTS]

        return Decision(
            draft_id=draft.get("id", "?"),
            activations=active,
            unknown_amenities=unknown,
            scores=scores,
            blocked=blocked,
            themes=winners,
            audience=audience,
            main_amenities=[domain.amenities[c]["db_name"] for c in main],
            secondary_amenities=[domain.amenities[c]["db_name"] for c in secondary],
            facts=facts,
            trace=trace,
        )
