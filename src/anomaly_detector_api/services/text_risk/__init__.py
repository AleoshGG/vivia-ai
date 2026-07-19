"""Subsistema de riesgo textual (Capa 0 reglas + Capa 1 LLM zero-shot).

Detecta redacción fraudulenta en título/descripción de un anuncio: contacto
directo (teléfono, correo, URL), evasión de la plataforma, urgencia o pago
directo. Porta la lógica validada en `notebooks/text_processing/text_risk.py`,
con backend HTTP al contenedor `llama-server`.
"""

from .text_risk_service import TextRiskService

__all__ = ["TextRiskService"]
