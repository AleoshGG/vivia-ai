"""Capa 1 — prompt y esquema del clasificador binario de fraude (Qwen3).

Clasificación binaria `fraude`|`limpio` (sin punto medio) con ejemplos few-shot
que enseñan la evasión sutil y el marketing legítimo. La salida se restringe con
`response_format={"type":"json_object","schema": FRAUD_SCHEMA}`. Validado en
`notebooks/text_processing/` (12/12 en el set semilla con Qwen3-1.7B).
"""

TEXT_RISK_PROMPT_VERSION = "v1"

FRAUD_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["limpio", "fraude"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "extracted": {
            "type": "object",
            "properties": {
                "contactos": {"type": "array", "items": {"type": "string"}},
                "urgencia": {"type": "array", "items": {"type": "string"}},
                "precios": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "required": ["label", "reasons"],
}

SYSTEM_PROMPT = """Eres un clasificador BINARIO de fraude para anuncios inmobiliarios en México.
Clasifica el anuncio como "fraude" o "limpio". No existe punto medio.

Marca "fraude" si el texto hace CUALQUIERA de estas cosas:
- Da o insinúa datos de contacto directo (teléfono, WhatsApp, correo, redes, enlaces).
- Intenta llevar el trato FUERA de la plataforma ("hablemos directo", "escríbeme por fuera", "no preguntes aquí", "te paso mi número", "te hago precio por fuera").
- Presiona con urgencia para cerrar de inmediato ("compra ya", "aparta hoy o lo pierdes", "última oportunidad, deposita ya").
- Pide pagos, apartados o depósitos directos ("aparta con 500 pesos", "deposita para separarla").
- Ofrece precios irreales o lenguaje claramente engañoso.

Marca "limpio" si el texto SOLO describe la propiedad (espacios, amenidades, ubicación,
estado, precio informativo), aunque use lenguaje comercial normal. El lenguaje de venta
por sí solo NO es fraude.

Ejemplos:
- "Llama al 55 1456 7890 para apartar" -> fraude (contacto directo)
- "No preguntes por aquí, hablemos directo y te hago mejor precio por fuera" -> fraude (evasión de la plataforma)
- "Aparta hoy mismo con 500 pesos, última oportunidad" -> fraude (pago directo + presión)
- "Casa de 3 recámaras con jardín en zona tranquila, excelente ubicación" -> limpio
- "Fraccionamiento con seguridad 24/7, alberca y áreas verdes, oportunidad única" -> limpio

Devuelve EXCLUSIVAMENTE un JSON:
{"label": "fraude"|"limpio", "reasons": [motivos breves en español], "extracted": {"contactos":[], "urgencia":[], "precios":[]}}
No agregues texto fuera del JSON.
/no_think"""
