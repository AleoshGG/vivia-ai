"""Motor de inferencia del grafo ponderado (v4).

Toma las decisiones editoriales ANTES del LLM: a partir del draft de la API transaccional,
activa nodos fuente, propaga pesos hacia temas y audiencias, aplica bloqueos (reglas de
negocio con peso −10) y produce un resumen prescriptivo compacto para que el modelo solo
redacte. Misma semántica que el simulador del visualizador (`generar_visualizador.py`):
k=2 temas, umbral 0.5, desempate por la arista contribuyente de mayor peso.

El dominio completo vive en `datasets/` (CSVs) — este módulo no tiene conocimiento propio.
Lo importan el notebook de experimentación, los tests y, después, el worker del servicio.
"""

from __future__ import annotations

import csv
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BLOQUEO = -10.0
PESOS_VALIDOS = {0.3, 0.6, 0.9}
PRIOR_MAX = 0.8

# Textos aprobados para los hechos derivados de buckets (espejo de buckets.csv).
HECHOS_BUCKET = {
    "a_estrenar": "a estrenar",
    "construccion_reciente": "construcción reciente",
    "con_historia": "más de 30 años: nombrarla como carácter e historia, sin afirmar estado",
    "area_amplia": "superficie amplia",
    "area_compacta": "espacio compacto y eficiente (no describir como amplio)",
    "en_condominio": "forma parte de un condominio",
    "sin_estacionamiento": "no mencionar estacionamientos",
}


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto).lower().strip())
    return "".join(c for c in texto if not unicodedata.combining(c))


@dataclass
class Arista:
    origen: str
    destino: str
    peso: float
    relacion: str  # evoca | prior | sugiere | bloquea
    porque: str = ""


@dataclass
class Dominio:
    amenidades: dict[str, dict]      # clave -> {nombre_db, aliases}
    temas: dict[str, dict]           # clave -> {frase_1, frase_2}
    tipos: dict[str, str]            # nombre BD -> narrativa
    operaciones: dict[str, str]      # RENTA/VENTA -> tono
    audiencias: dict[str, str]       # clave -> frase
    buckets: dict[str, str]          # clave -> condicion (documental)
    aristas: list[Arista]
    alias_a_amenidad: dict[str, str] = field(default_factory=dict)
    _por_origen: dict[str, list[Arista]] = field(default_factory=dict)

    def __post_init__(self):
        for nodo, d in self.amenidades.items():
            for alias in d["aliases"] + [d["nombre_db"]]:
                if alias:
                    self.alias_a_amenidad[_normalizar(alias)] = nodo
        for a in self.aristas:
            self._por_origen.setdefault(a.origen, []).append(a)

    def aristas_de(self, origen: str) -> list[Arista]:
        return self._por_origen.get(origen, [])


@dataclass
class Decision:
    draft_id: str
    activaciones: list[str]
    desconocidas: list[str]
    scores: dict[str, float]                 # tema -> score acumulado
    bloqueados: dict[str, list[Arista]]      # tema -> bloqueos aplicados
    temas: list[str]                         # ganadores, en orden
    audiencia: str | None
    protagonistas: list[str]                 # nombres BD de amenidades a destacar
    secundarias: list[str]
    hechos: list[str]
    traza: list[str]                         # bitácora legible de la propagación


# ─────────────────────────────────────────────────────────────────────────────
# Carga y validación del dominio
# ─────────────────────────────────────────────────────────────────────────────

def _leer(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cargar_dominio(ruta_datasets: Path | str) -> Dominio:
    """Lee los CSVs de datasets/ y valida claves y escalas. Falla temprano si algo no cuadra."""
    ds = Path(ruta_datasets)
    amenidades = {r["amenidad"]: {"nombre_db": r["nombre_db"],
                                  "aliases": [a for a in r["aliases"].split("|") if a]}
                  for r in _leer(ds / "amenidades.csv")}
    temas = {r["tema"]: {"frase_1": r["frase_1"], "frase_2": r["frase_2"]}
             for r in _leer(ds / "temas.csv")}
    tipos = {r["tipo"]: r["narrativa"] for r in _leer(ds / "tipos_propiedad.csv")}
    operaciones = {r["operacion"]: r["tono"] for r in _leer(ds / "operaciones.csv")}
    audiencias = {r["audiencia"]: r["frase"] for r in _leer(ds / "audiencias.csv")}
    buckets = {r["bucket"]: r["condicion"] for r in _leer(ds / "buckets.csv")}

    fuentes = set(buckets) | set(tipos) | set(operaciones)
    errores: list[str] = []
    aristas: list[Arista] = []

    for r in _leer(ds / "pesos_evoca.csv"):
        amenidad = r.pop("amenidad")
        if amenidad not in amenidades:
            errores.append(f"pesos_evoca: amenidad desconocida '{amenidad}'")
            continue
        for tema, celda in r.items():
            if not celda:
                continue
            peso = float(celda)
            if tema not in temas:
                errores.append(f"pesos_evoca: tema desconocido '{tema}'")
            elif peso not in PESOS_VALIDOS:
                errores.append(f"pesos_evoca: peso fuera de escala {peso} en {amenidad}→{tema}")
            else:
                aristas.append(Arista(f"am:{amenidad}", tema, peso, "evoca"))

    for r in _leer(ds / "pesos_priors.csv"):
        peso = float(r["peso"])
        if r["origen"] not in fuentes:
            errores.append(f"pesos_priors: origen desconocido '{r['origen']}'")
        elif r["tema"] not in temas:
            errores.append(f"pesos_priors: tema desconocido '{r['tema']}'")
        elif peso > PRIOR_MAX:
            errores.append(f"pesos_priors: prior {peso} > {PRIOR_MAX} en {r['origen']}→{r['tema']}")
        else:
            aristas.append(Arista(f"src:{r['origen']}", r["tema"], peso, "prior"))

    for r in _leer(ds / "reglas_audiencia.csv"):
        if r["origen"] not in fuentes:
            errores.append(f"reglas_audiencia: origen desconocido '{r['origen']}'")
        elif r["audiencia"] not in audiencias:
            errores.append(f"reglas_audiencia: audiencia desconocida '{r['audiencia']}'")
        else:
            aristas.append(Arista(f"src:{r['origen']}", f"aud:{r['audiencia']}",
                                   float(r["peso"]), "sugiere"))

    for r in _leer(ds / "bloqueos.csv"):
        if r["origen"] not in fuentes:
            errores.append(f"bloqueos: origen desconocido '{r['origen']}'")
        elif r["tema_bloqueado"] not in temas:
            errores.append(f"bloqueos: tema desconocido '{r['tema_bloqueado']}'")
        else:
            aristas.append(Arista(f"src:{r['origen']}", r["tema_bloqueado"],
                                   BLOQUEO, "bloquea", r["porque"]))

    if errores:
        raise ValueError("Dominio inválido:\n- " + "\n- ".join(errores))
    return Dominio(amenidades, temas, tipos, operaciones, audiencias, buckets, aristas)


# ─────────────────────────────────────────────────────────────────────────────
# Activación del draft
# ─────────────────────────────────────────────────────────────────────────────

def buckets_de(draft: dict, año_actual: int | None = None) -> list[str]:
    """Discretiza el draft (espejo de las condiciones documentadas en buckets.csv)."""
    año = año_actual or date.today().year
    antiguedad = año - draft["constructionYear"]
    b = []
    if antiguedad <= 1:
        b.append("a_estrenar")
    elif antiguedad <= 10:
        b.append("construccion_reciente")
    if antiguedad > 30:
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


def activar(dominio: Dominio, draft: dict, año_actual: int | None = None):
    """Nodos fuente activados por el draft + amenidades sin resolver."""
    operacion = "RENTA" if draft["availableToRent"] else "VENTA"
    activos = [f"src:{operacion}"]
    tipo = next((t for t in dominio.tipos if _normalizar(t) == _normalizar(draft["propertyType"]["name"])), None)
    if tipo:
        activos.append(f"src:{tipo}")
    activos += [f"src:{b}" for b in buckets_de(draft, año_actual)]
    desconocidas = []
    for amenidad in draft.get("amenities", []):
        clave = dominio.alias_a_amenidad.get(_normalizar(amenidad))
        if clave:
            activos.append(f"am:{clave}")
        else:
            desconocidas.append(amenidad)
    return activos, desconocidas, operacion, tipo


# ─────────────────────────────────────────────────────────────────────────────
# Propagación, selección y resumen
# ─────────────────────────────────────────────────────────────────────────────

def inferir(dominio: Dominio, draft: dict, k: int = 2, umbral: float = 0.5,
            año_actual: int | None = None) -> Decision:
    activos, desconocidas, operacion, tipo = activar(dominio, draft, año_actual)

    scores: dict[str, float] = {}
    contribuciones: dict[str, list[Arista]] = {}
    bloqueados: dict[str, list[Arista]] = {}
    traza: list[str] = [f"activaciones: {', '.join(a.split(':', 1)[1] for a in activos)}"]

    for origen in activos:
        for a in dominio.aristas_de(origen):
            scores[a.destino] = scores.get(a.destino, 0.0) + a.peso
            contribuciones.setdefault(a.destino, []).append(a)
            if a.relacion == "bloquea":
                bloqueados.setdefault(a.destino, []).append(a)
                traza.append(f"BLOQUEO {a.destino} ⊣ {origen.split(':', 1)[1]}: {a.porque}")
            else:
                traza.append(f"{origen.split(':', 1)[1]} → {a.destino} (+{a.peso})")

    def max_contrib(destino: str) -> float:
        return max((a.peso for a in contribuciones.get(destino, []) if a.relacion != "bloquea"),
                   default=0.0)

    # Temas: score desc, desempate por arista contribuyente máxima; bloqueado descalifica.
    ranking = sorted(dominio.temas, key=lambda t: (-scores.get(t, 0.0), -max_contrib(t)))
    ganadores = [t for t in ranking if t not in bloqueados and scores.get(t, 0.0) >= umbral][:k]
    traza.append(f"temas ganadores (k={k}, umbral={umbral}): {ganadores}")

    # Audiencia: top-1 con score > 0; desempate por contribución máxima y orden del catálogo.
    orden_aud = list(dominio.audiencias)
    aud_rank = sorted(orden_aud, key=lambda a: (-scores.get(f"aud:{a}", 0.0),
                                                -max_contrib(f"aud:{a}"), orden_aud.index(a)))
    audiencia = aud_rank[0] if scores.get(f"aud:{aud_rank[0]}", 0.0) > 0 else None
    traza.append(f"audiencia: {audiencia}")

    # Amenidades protagonistas: las que más contribuyen a los temas ganadores.
    contribuyentes: dict[str, float] = {}
    for tema in ganadores:
        for a in contribuciones.get(tema, []):
            if a.relacion == "evoca":
                clave = a.origen.split(":", 1)[1]
                contribuyentes[clave] = max(contribuyentes.get(clave, 0.0), a.peso)
    protagonistas = sorted(contribuyentes, key=lambda c: -contribuyentes[c])[:2]
    conocidas = [dominio.alias_a_amenidad[_normalizar(x)] for x in draft.get("amenities", [])
                 if _normalizar(x) in dominio.alias_a_amenidad]
    secundarias = [c for c in conocidas if c not in protagonistas]

    hechos = [HECHOS_BUCKET[b] for b in buckets_de(draft, año_actual) if b in HECHOS_BUCKET]

    return Decision(
        draft_id=draft.get("id", "?"),
        activaciones=activos,
        desconocidas=desconocidas,
        scores=scores,
        bloqueados=bloqueados,
        temas=ganadores,
        audiencia=audiencia,
        protagonistas=[dominio.amenidades[c]["nombre_db"] for c in protagonistas],
        secundarias=[dominio.amenidades[c]["nombre_db"] for c in secundarias],
        hechos=hechos,
        traza=traza,
    )


def resumen_para_llm(dominio: Dominio, draft: dict, decision: Decision) -> str:
    """El bloque prescriptivo (~70-100 tokens) — lo único que ve el LLM además del draft."""
    operacion = "RENTA" if draft["availableToRent"] else "VENTA"
    tipo = next((t for t in dominio.tipos if _normalizar(t) == _normalizar(draft["propertyType"]["name"])), None)
    lineas = ["DECISIONES DE REDACCIÓN (obligatorias):"]
    if tipo:
        lineas.append(f"- Narrativa: {tipo.lower()} — {dominio.tipos[tipo]}.")
    lineas.append(f"- Tono: {dominio.operaciones[operacion]}.")
    if decision.audiencia:
        lineas.append(f"- Audiencia: {dominio.audiencias[decision.audiencia]}.")
    if decision.temas:
        partes = [f"{i + 1}) {t.replace('_', ' ')} — parafrasea: \"{dominio.temas[t]['frase_1']}\""
                  for i, t in enumerate(decision.temas)]
        lineas.append(f"- Temas en orden: {'; '.join(partes)}.")
    if decision.protagonistas:
        linea = f"- Amenidades protagonistas: {', '.join(decision.protagonistas)}."
        if decision.secundarias:
            linea += f" Secundarias (solo de pasada): {', '.join(decision.secundarias)}."
        lineas.append(linea)
    if decision.desconocidas:
        lineas.append(f"- Amenidades sin ángulo aprobado (menciónalas solo por su nombre): "
                      f"{', '.join(decision.desconocidas)}.")
    if decision.hechos:
        lineas.append(f"- Hechos: {'; '.join(decision.hechos)}.")
    return "\n".join(lineas)


def draft_json_a_texto(draft: dict, año_actual: int | None = None) -> str:
    """Draft de la API → texto para el modelo. Excluye precio, calle/números e ids."""
    año = año_actual or date.today().year
    operacion = "RENTA" if draft["availableToRent"] else "VENTA"
    antiguedad = año - draft["constructionYear"]
    lineas = [
        f"Tipo de propiedad: {draft['propertyType']['name']}",
        f"Operación: {operacion}",
        f"Colonia: {draft['address']['neighborhoodName']}",
        f"Superficie: {draft['areaM2']:.0f} m²",
    ]
    # Los campos en cero se omiten: lo que el modelo no ve, no lo redacta.
    if draft["bedrooms"] > 0:
        lineas.append(f"Recámaras: {draft['bedrooms']}")
    if draft["bathrooms"] > 0:
        lineas.append(f"Baños: {draft['bathrooms']}")
    if draft["parkingSpaces"] > 0:
        lineas.append(f"Estacionamientos: {draft['parkingSpaces']}")
    lineas.append(
        f"Año de construcción: {draft['constructionYear']}"
        + (f" ({antiguedad} años de antigüedad)" if antiguedad > 1 else " (a estrenar)")
    )
    if draft["condominium"]:
        lineas.append("En condominio: sí")
    if draft.get("amenities"):
        lineas.append(f"Amenidades: {', '.join(draft['amenities'])}")
    return "\n".join(lineas)


def cargar_drafts(ruta: Path | str) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return [d["draft"] for d in json.load(f)]
