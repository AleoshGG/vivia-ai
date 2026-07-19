"""Fusión del subsistema de riesgo textual (Decision Engine textual).

Orquesta Capa 0 (reglas) y Capa 1 (LLM) en un veredicto binario:
`is_fraud_text = regla_dura ∨ (label == "fraude")`.

- Contacto directo (teléfono/correo/URL) → fraude sin consultar al LLM (barato,
  altísima precisión y evita cargar el `llama-server`).
- Sin bloqueo duro → decide el LLM. Si el LLM no está disponible, degrada a un
  criterio conservador (solo precio Y urgencia juntos disparan fraude).
"""

from __future__ import annotations

import logging

from ...models.text_risk import TextRiskResult
from .llm_text_client import LlamaTextRiskClient
from .rules import evaluate_rules, reasons_from_rules

logger = logging.getLogger(__name__)


class TextRiskService:
    def __init__(self, client: LlamaTextRiskClient, *, enabled: bool = True):
        self._client = client
        self._enabled = enabled

    async def evaluate(self, title: str, description: str) -> TextRiskResult:
        sig = evaluate_rules(title, description)
        reglas = reasons_from_rules(sig)

        # Bloqueo duro: contacto directo -> fraude sin consultar al LLM.
        if sig.has_hard_contact:
            return TextRiskResult("fraude", True, reglas, "rules")

        verdict = await self._client.classify(title, description) if self._enabled else None

        if verdict is None:
            # Sin LLM: conservador. Solo precio + urgencia juntos disparan fraude.
            is_fraud = bool(sig.price_hits and sig.cta_hits)
            label = "fraude" if is_fraud else "limpio"
            return TextRiskResult(label, is_fraud, reglas, "rules")

        reasons = reglas + [r for r in verdict.reasons if r not in reglas]
        source = "both" if reglas else "llm"
        return TextRiskResult(verdict.label, verdict.is_fraud, reasons, source)
