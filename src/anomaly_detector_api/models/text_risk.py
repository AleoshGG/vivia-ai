"""Modelos internos del subsistema de riesgo textual.

Objetos de dominio (no esquemas de API): describen el resultado de las reglas
deterministas (Capa 0), el veredicto del LLM (Capa 1) y la fusión binaria final.
Espejan la lógica validada en `notebooks/text_processing/text_risk.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuleSignals:
    """Coincidencias de la Capa 0 (reglas deterministas)."""

    phones: list = field(default_factory=list)
    emails: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    price_hits: list = field(default_factory=list)
    cta_hits: list = field(default_factory=list)

    @property
    def has_hard_contact(self) -> bool:
        """Bloqueo duro: contacto directo (teléfono, correo o URL)."""
        return bool(self.phones or self.emails or self.urls)


@dataclass
class LlmVerdict:
    """Veredicto binario del LLM (Capa 1)."""

    label: str  # "limpio" | "fraude"
    reasons: list = field(default_factory=list)
    extracted: dict = field(default_factory=dict)

    @property
    def is_fraud(self) -> bool:
        return self.label == "fraude"


@dataclass
class TextRiskResult:
    """Resultado fusionado del subsistema de riesgo textual."""

    label: str  # "fraude" | "limpio"
    is_fraud_text: bool
    reasons: list = field(default_factory=list)
    source: str = "rules"  # "rules" | "llm" | "both"
