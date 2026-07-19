"""Capa 0 — reglas deterministas sobre el texto.

Normaliza y des-ofusca el texto antes de extraer, para que los trucos de
redacción (números escritos, 'arroba'/'punto', separadores en teléfonos) no
evadan la detección. Los patrones `RE_PRECIO`/`RE_CONTACTO` reutilizan los ya
validados en los notebooks del grafo y en `llm_local_service`.
"""

from __future__ import annotations

import re
import unicodedata

from ...models.text_risk import RuleSignals

# --- Normalización y des-ofuscación -----------------------------------------
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


# --- Extractores ------------------------------------------------------------
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


def _matches(rx: re.Pattern, t: str) -> list[str]:
    return [m.group(0) for m in rx.finditer(t)]


def evaluate_rules(title: str, description: str) -> RuleSignals:
    """Extrae señales deterministas de contacto/precio/urgencia del texto."""
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


def reasons_from_rules(sig: RuleSignals) -> list[str]:
    """Motivos legibles a partir de las señales de reglas."""
    r: list[str] = []
    if sig.phones:
        r.append(f"Incluye teléfono de contacto: {', '.join(sig.phones)}")
    if sig.emails:
        r.append(f"Incluye correo de contacto: {', '.join(sig.emails)}")
    if sig.urls:
        r.append(f"Incluye enlace/dominio externo: {', '.join(sig.urls)}")
    if sig.price_hits:
        r.append("Menciona precio o pago directo")
    if sig.cta_hits:
        r.append("Lenguaje de urgencia / llamado a la acción")
    return r
