"""Pipeline de riesgo textual (prototipo) — Capa 0 reglas + Capa 1 LLM zero-shot.

Versión consolidada de la lógica explorada en `01_text_processing.ipynb`, para
reutilizarla desde `02_fusion_isolation_forest.ipynb` sin duplicar código. Es,
en esencia, el borrador del futuro `TextRiskService` del servicio
`anomaly_detector_api`.

Clasificación **binaria**: `fraude` | `limpio` (sin punto medio). La decisión
final es `is_fraud_text`; no hay umbral numérico que calibrar.

Backend del LLM configurable (`LLM_BACKEND`):
- "llama_cpp": carga el GGUF en proceso con llama-cpp-python (autónomo).
- "server":    HTTP a un llama-server ya levantado.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# --- Configuración -----------------------------------------------------------
USE_LLM = True
LLM_BACKEND = "llama_cpp"  # "llama_cpp" | "server"

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models_registry" / "llm"
MODEL_PATH = str(_MODELS_DIR / "Qwen3-1.7B-Q4_K_M.gguf")
N_CTX = 4096
N_THREADS = 4

LLAMA_URL = "http://127.0.0.1:8080"
LLM_TIMEOUT_S = 60

# --- Etapa 0: normalización y des-ofuscación --------------------------------
_NUM_PALABRA = {
    "cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
}
_RX_NUM_PALABRA = re.compile(r"\b(" + "|".join(_NUM_PALABRA) + r")\b")
_TLD = r"(?:com|mx|net|org|io|co|info|biz)"


def _numeros_escritos(t: str) -> str:
    return _RX_NUM_PALABRA.sub(lambda m: _NUM_PALABRA[m.group(0)], t)


def normalizar(texto: str) -> str:
    """NFKC + minúsculas + números escritos a dígitos."""
    t = unicodedata.normalize("NFKC", texto or "").lower()
    return _numeros_escritos(t)


def desofuscar(t: str) -> str:
    """Reconstruye correos/URLs ofuscados: 'arroba' -> '@', 'punto com' -> '.com'."""
    t = re.sub(r"\s*\(?\s*arroba\s*\)?\s*", "@", t)
    t = re.sub(r"\s*punto\s*(" + _TLD + r")\b", r".\1", t)
    return t


def colapsar_telefono(t: str) -> str:
    """Une dígitos separados por espacios/.-() para reconstruir teléfonos."""
    return re.sub(r"(?<=\d)[\s.\-()]+(?=\d)", "", t)


# --- Etapa 1: Capa 0, extractores deterministas -----------------------------
RE_PRECIO = re.compile(
    r"\$|\bprecio\b|\bmxn\b|\bpesos?\b|mensualidad|mill[oó]n|\bmonto\b", re.I
)
RE_CONTACTO = re.compile(
    r"cont[aá]ct|ll[aá]m[ae]|tel[eé]fono|whatsapp|escr[ií]b[ae]|agend[ae]|vis[ií]t[ae]|"
    r"aprovecha|no te lo pierdas|[uú]ltimos d[ií]as|cita|oportunidad [uú]nica", re.I
)
RE_EMAIL = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}")
RE_URL = re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9\-]+\." + _TLD + r"\b")
RE_TEL = re.compile(r"(?:\+?52|0?4[45])?\d{10,13}")


def _matches(rx, t):
    return [m.group(0) for m in rx.finditer(t)]


@dataclass
class RuleSignals:
    phones: list = field(default_factory=list)
    emails: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    price_hits: list = field(default_factory=list)
    cta_hits: list = field(default_factory=list)

    @property
    def has_hard_contact(self) -> bool:
        return bool(self.phones or self.emails or self.urls)


def evaluate_rules(title: str, description: str) -> RuleSignals:
    base = normalizar(f"{title}\n{description or ''}")
    desof = desofuscar(base)
    tel = colapsar_telefono(desof)
    return RuleSignals(
        phones=_matches(RE_TEL, tel),
        emails=_matches(RE_EMAIL, desof),
        urls=_matches(RE_URL, desof),
        price_hits=_matches(RE_PRECIO, base),
        cta_hits=_matches(RE_CONTACTO, base),
    )


# --- Etapa 2: Capa 1, LLM zero-shot binario (JSON) --------------------------
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


@dataclass
class LlmVerdict:
    label: str
    reasons: list
    extracted: dict = field(default_factory=dict)

    @property
    def is_fraud(self) -> bool:
        return self.label == "fraude"


def _parse_verdict(content: str) -> LlmVerdict:
    data = json.loads(content)
    label = data.get("label", "limpio")
    return LlmVerdict(
        label=label if label in ("limpio", "fraude") else "limpio",
        reasons=data.get("reasons", []),
        extracted=data.get("extracted", {}),
    )


_LLM = None  # instancia perezosa; se carga una sola vez


def _get_llama():
    global _LLM
    if _LLM is None:
        from llama_cpp import Llama
        print(f"Cargando GGUF: {MODEL_PATH} (n_ctx={N_CTX}, n_threads={N_THREADS})...")
        _LLM = Llama(
            model_path=MODEL_PATH,
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            n_gpu_layers=0,
            verbose=False,
        )
        print("Modelo cargado.")
    return _LLM


def _user_msg(title: str, description: str) -> str:
    return f'TÍTULO: {title}\nDESCRIPCIÓN: {description or ""}'


def _classify_llama_cpp(title: str, description: str) -> LlmVerdict:
    out = _get_llama().create_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_msg(title, description)},
        ],
        temperature=0.1,
        top_p=0.8,
        max_tokens=400,
        response_format={"type": "json_object", "schema": FRAUD_SCHEMA},
    )
    return _parse_verdict(out["choices"][0]["message"]["content"])


def _classify_server(title: str, description: str) -> LlmVerdict:
    import requests
    payload = {
        "model": "local",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_msg(title, description)},
        ],
        "temperature": 0.1,
        "top_p": 0.8,
        "max_tokens": 400,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object", "schema": FRAUD_SCHEMA},
    }
    r = requests.post(f"{LLAMA_URL}/v1/chat/completions", json=payload, timeout=LLM_TIMEOUT_S)
    r.raise_for_status()
    return _parse_verdict(r.json()["choices"][0]["message"]["content"])


def classify_llm(title: str, description: str) -> "LlmVerdict | None":
    """Despacha al backend configurado; degrada a None si el modelo no está."""
    try:
        if LLM_BACKEND == "llama_cpp":
            return _classify_llama_cpp(title, description)
        return _classify_server(title, description)
    except Exception as exc:
        print(f"[LLM no disponible -> solo reglas] {type(exc).__name__}: {exc}")
        return None


# --- Etapa 3: fusión textual -> TextRiskResult ------------------------------
@dataclass
class TextRiskResult:
    label: str            # "fraude" | "limpio"
    is_fraud_text: bool
    reasons: list
    source: str           # "rules" | "llm" | "both"


def _reasons_reglas(sig: RuleSignals) -> list:
    r = []
    if sig.phones: r.append(f"Incluye teléfono de contacto: {', '.join(sig.phones)}")
    if sig.emails: r.append(f"Incluye correo de contacto: {', '.join(sig.emails)}")
    if sig.urls: r.append(f"Incluye enlace/dominio externo: {', '.join(sig.urls)}")
    if sig.price_hits: r.append("Menciona precio o pago directo")
    if sig.cta_hits: r.append("Lenguaje de urgencia / llamado a la acción")
    return r


def evaluate_text_risk(title: str, description: str, use_llm: bool | None = None) -> TextRiskResult:
    if use_llm is None:
        use_llm = USE_LLM
    sig = evaluate_rules(title, description)
    reglas = _reasons_reglas(sig)

    # Regla dura: contacto directo -> fraude sin consultar al LLM.
    if sig.has_hard_contact:
        return TextRiskResult("fraude", True, reglas, "rules")

    verdict = classify_llm(title, description) if use_llm else None

    if verdict is None:
        # Sin LLM: conservador. Solo precio + urgencia juntos disparan fraude.
        is_fraud = bool(sig.price_hits and sig.cta_hits)
        label = "fraude" if is_fraud else "limpio"
        return TextRiskResult(label, is_fraud, reglas, "rules")

    is_fraud = verdict.is_fraud
    reasons = reglas + [x for x in verdict.reasons if x not in reglas]
    source = "both" if reglas else "llm"
    return TextRiskResult(verdict.label, is_fraud, reasons, source)
