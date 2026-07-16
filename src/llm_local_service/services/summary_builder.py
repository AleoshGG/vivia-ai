"""Construcción del mensaje al LLM a partir de la decisión del grafo.

Única responsabilidad: producir el bloque prescriptivo de DECISIONES DE
REDACCIÓN (~70-100 tokens) — en el contrato v6 es lo ÚNICO que ve el LLM
(el draft crudo nunca viaja al modelo) — y cargar el system prompt versionado
desde `resources/prompts/`.
"""

from __future__ import annotations

from pathlib import Path

from ..models.graph import Decision, Domain
from .graph_loader import normalize

PROMPT_VERSION = "v6"
GRAPH_VERSION = "v4"


def load_system_prompt(resources_path: Path | str) -> str:
    """Lee el system prompt versionado (artefacto registrado en MLflow)."""
    prompt_file = Path(resources_path) / "prompts" / f"system_prompt_{PROMPT_VERSION}.txt"
    return prompt_file.read_text(encoding="utf-8").strip()


def build_summary(domain: Domain, draft: dict, decision: Decision) -> str:
    """El bloque prescriptivo que recibe el LLM como mensaje de usuario."""
    operation = "RENTA" if draft["availableToRent"] else "VENTA"
    prop_type = next(
        (t for t in domain.property_types
         if normalize(t) == normalize(draft["propertyType"]["name"])),
        None,
    )
    lines = ["DECISIONES DE REDACCIÓN (obligatorias):"]
    if prop_type:
        lines.append(f"- Narrativa: {prop_type.lower()} — {domain.property_types[prop_type]}.")
    lines.append(f"- Tono: {domain.operations[operation]}.")
    if decision.audience:
        lines.append(f"- Audiencia: {domain.audiences[decision.audience]}.")
    if decision.themes:
        parts = [f"{i + 1}) {t.replace('_', ' ')} — parafrasea: \"{domain.themes[t]['frase_1']}\""
                 for i, t in enumerate(decision.themes)]
        lines.append(f"- Temas en orden: {'; '.join(parts)}.")
    if decision.main_amenities:
        line = f"- Amenidades protagonistas: {', '.join(decision.main_amenities)}."
        if decision.secondary_amenities:
            line += f" Secundarias (solo de pasada): {', '.join(decision.secondary_amenities)}."
        lines.append(line)
    if decision.unknown_amenities:
        lines.append(f"- Amenidades sin ángulo aprobado (menciónalas solo por su nombre): "
                     f"{', '.join(decision.unknown_amenities)}.")
    if decision.facts:
        lines.append(f"- Hechos: {'; '.join(decision.facts)}.")
    return "\n".join(lines)
