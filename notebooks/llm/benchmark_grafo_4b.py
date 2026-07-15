"""Benchmark: Qwen3-4B + grafo de conocimiento (pipeline v3) fuera de notebook.

Ejecuta N inferencias de {titulo, descripcion} sobre los drafts de ejemplo, midiendo el
tiempo de cada etapa del pipeline (parseo del draft, consulta del grafo, inferencia LLM,
parseo de salida). Los resultados por inferencia se escriben a un CSV y la bitácora de
tiempos a un TXT.

Uso (desde notebooks/llm/, con el venv de notebooks):
    ../.venv/bin/python benchmark_grafo_4b.py                 # 100 inferencias, 4 hilos
    ../.venv/bin/python benchmark_grafo_4b.py --inferencias 10 --threads 2

Concurrencia: los hilos (--threads) son los hilos nativos de llama.cpp DENTRO de cada
inferencia (paralelismo de matrices). Las inferencias van secuenciales a propósito: en CPU
el cuello es el ancho de banda de memoria y paralelizar peticiones no mejora el throughput
(además duplicaría la RAM). Es el mismo modelo de ejecución que tendrá el worker en el VPS.
"""

import argparse
import csv
import json
import logging
import re
import statistics
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import networkx as nx
import psutil
from llama_cpp import Llama

BASE = Path(__file__).resolve().parent
AÑO_ACTUAL = date.today().year

# ═════════════════════════════════════════════════════════════════════════════
# [1] VARIABLES
# ═════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Qwen3-4B + grafo de dominio")
    parser.add_argument("--inferencias", type=int, default=100,
                        help="número de inferencias a ejecutar (default: 100)")
    parser.add_argument("--threads", type=int, default=4,
                        help="hilos nativos de llama.cpp por inferencia (default: 4)")
    parser.add_argument("--ctx", type=int, default=4096,
                        help="tamaño de contexto n_ctx (default: 4096)")
    parser.add_argument("--modelo", type=Path,
                        default=BASE / "../../models_registry/llm/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
                        help="ruta al GGUF")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    return parser.parse_args()


SYSTEM_PROMPT_V3 = """Eres un redactor inmobiliario profesional de México. Recibirás el DRAFT de una \
propiedad y un bloque de HECHOS Y ÁNGULOS APROBADOS. Escribirás el anuncio para un portal inmobiliario.

Reglas estrictas:
1. Usa ÚNICAMENTE la información del DRAFT y de los HECHOS Y ÁNGULOS APROBADOS. Puedes \
parafrasear las frases aprobadas con naturalidad, pero NO agregues características, lugares, \
vistas, cercanías ni cualidades que no aparezcan ahí.
2. PROHIBIDO mencionar precios, montos, rentas, mensualidades o cualquier cifra monetaria.
3. PROHIBIDO incluir datos de contacto, invitaciones a llamar, escribir o agendar visitas, \
y lenguaje de urgencia ("aprovecha", "no te lo pierdas", "últimos días", "oportunidad única").
4. La única ubicación que puedes mencionar es el nombre de la colonia, tal como aparece en el draft.
5. Usa español de México y vocabulario de la región: "recámaras" (nunca "habitaciones") y \
"estacionamientos" (nunca "cajones de estacionamiento" ni "plazas de garaje"). Si el draft no \
menciona estacionamientos, no hables de ellos.
6. El título debe tener máximo 10 palabras, atractivo sin ser sensacionalista.
7. La descripción debe tener entre 21 y 70 palabras, en párrafos fluidos (sin listas), \
con tono cálido y humano, sin mayúsculas sostenidas ni signos de admiración excesivos.

Responde exclusivamente con un JSON con las claves "titulo" y "descripcion"."""

ESQUEMA_ANUNCIO = {
    "type": "object",
    "properties": {"titulo": {"type": "string"}, "descripcion": {"type": "string"}},
    "required": ["titulo", "descripcion"],
}

RE_PRECIO = re.compile(r"\$|\bprecio\b|\bmxn\b|\bpesos?\b|mensualidad|mill[oó]n|\bmonto\b", re.I)
RE_CONTACTO = re.compile(
    r"cont[aá]ct|ll[aá]m[ae]|tel[eé]fono|whatsapp|escr[ií]b[ae]|agend[ae]|vis[ií]t[ae]|"
    r"aprovecha|no te lo pierdas|[uú]ltimos d[ií]as|cita|oportunidad [uú]nica", re.I)


def configurar_log(ruta_txt: Path) -> logging.Logger:
    logger = logging.getLogger("benchmark")
    logger.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    for handler in (logging.FileHandler(ruta_txt, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formato)
        logger.addHandler(handler)
    return logger


# ═════════════════════════════════════════════════════════════════════════════
# [2] MONTAJE DEL GRAFO Y PIPELINE
# ═════════════════════════════════════════════════════════════════════════════

def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower().strip())
    return "".join(c for c in texto if not unicodedata.combining(c))


def montar_grafo(logger: logging.Logger) -> tuple[nx.DiGraph, dict]:
    t0 = time.perf_counter()
    with open(BASE / "grafo_dominio.json") as f:
        G = nx.node_link_graph(json.load(f), edges="edges")
    alias = {
        _normalizar(a): nodo
        for nodo, data in G.nodes(data=True) if data["tipo"] == "amenidad"
        for a in data["aliases"] + [data["nombre"]]
    }
    logger.info(f"[2] Grafo montado en {(time.perf_counter() - t0) * 1000:.1f} ms — "
                f"{G.number_of_nodes()} nodos, {G.number_of_edges()} aristas, {len(alias)} aliases")
    conteo = {}
    for _, d in G.nodes(data=True):
        conteo[d["tipo"]] = conteo.get(d["tipo"], 0) + 1
    logger.info(f"[2] Nodos por tipo: {conteo}")
    return G, alias


def draft_json_a_texto(draft: dict) -> str:
    operacion = "RENTA" if draft["availableToRent"] else "VENTA"
    antiguedad = AÑO_ACTUAL - draft["constructionYear"]
    lineas = [
        f"Tipo de propiedad: {draft['propertyType']['name']}",
        f"Operación: {operacion}",
        f"Colonia: {draft['address']['neighborhoodName']}",
        f"Superficie: {draft['areaM2']:.0f} m²",
        f"Recámaras: {draft['bedrooms']}",
        f"Baños: {draft['bathrooms']}",
    ]
    if draft["parkingSpaces"] > 0:
        lineas.append(f"Estacionamientos: {draft['parkingSpaces']}")
    lineas.append(
        f"Año de construcción: {draft['constructionYear']}"
        + (f" ({antiguedad} años de antigüedad)" if antiguedad > 1 else " (a estrenar)")
    )
    lineas.append(f"En condominio: {'sí' if draft['condominium'] else 'no'}")
    if draft["amenities"]:
        lineas.append(f"Amenidades: {', '.join(draft['amenities'])}")
    return "\n".join(lineas)


def audiencias_para(draft: dict) -> list[str]:
    tipo = draft["propertyType"]["name"]
    rec, renta = draft["bedrooms"], draft["availableToRent"]
    if rec >= 4 or (rec >= 3 and tipo == "CASA"):
        return ["audiencia:familia_grande"]
    if rec >= 2:
        return ["audiencia:familia_pareja"]
    if renta:
        return ["audiencia:profesionista", "audiencia:persona_sola"]
    return ["audiencia:persona_sola"]


def contexto_desde_grafo(G: nx.DiGraph, alias: dict, draft: dict) -> str:
    lineas = ["HECHOS Y ÁNGULOS APROBADOS (única fuente permitida además del draft):"]
    temas_usados: set[str] = set()

    op = "RENTA" if draft["availableToRent"] else "VENTA"
    lineas.append(f"- Operación {op}: {G.nodes[f'operacion:{op}']['tono']}.")
    nodo_tipo = f"tipo:{draft['propertyType']['name']}"
    if nodo_tipo in G:
        lineas.append(f"- Un(a) {draft['propertyType']['name'].lower()} {G.nodes[nodo_tipo]['narrativa']}.")
        temas_usados.update(G.successors(nodo_tipo))

    desconocidas = []
    for amenidad in draft["amenities"]:
        nodo = alias.get(_normalizar(amenidad))
        if nodo is None:
            desconocidas.append(amenidad)
            continue
        for tema in G.successors(nodo):
            if tema in temas_usados:
                continue
            temas_usados.add(tema)
            frase = G.nodes[tema]["frases"][0]
            lineas.append(f"- {G.nodes[nodo]['nombre']} → {G.nodes[tema]['nombre']}: \"{frase}\".")
    if desconocidas:
        lineas.append(f"- Amenidades sin ángulo aprobado (menciónalas SOLO por su nombre): {', '.join(desconocidas)}.")

    frases_aud = [G.nodes[a]["frase"] for a in audiencias_para(draft)]
    lineas.append(f"- Audiencia sugerida: {'; '.join(frases_aud)}.")

    antiguedad = AÑO_ACTUAL - draft["constructionYear"]
    if antiguedad <= 1:
        lineas.append("- Antigüedad: a estrenar — puedes destacar que es de reciente construcción.")
    elif antiguedad <= 10:
        lineas.append("- Antigüedad: construcción reciente.")
    elif antiguedad > 30:
        lineas.append("- Antigüedad: más de 30 años — nómbrala como carácter e historia; "
                      "NO afirmes remodelaciones ni buen estado que el draft no indica.")
    if draft["areaM2"] >= 180:
        lineas.append("- Superficie: puedes describirla como amplia.")
    elif draft["areaM2"] <= 50:
        lineas.append("- Superficie: descríbela como compacta y eficiente, no como amplia.")
    return "\n".join(lineas)


# ═════════════════════════════════════════════════════════════════════════════
# MAIN — etapas [1] a [5]
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    args = parse_args()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_csv = BASE / f"benchmark_4b_{marca}.csv"
    ruta_txt = BASE / f"benchmark_4b_{marca}.log.txt"
    logger = configurar_log(ruta_txt)
    proceso = psutil.Process()

    # ── [1] Variables ────────────────────────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[1] VARIABLES")
    logger.info(f"[1] modelo={args.modelo.name} | inferencias={args.inferencias} | "
                f"threads(llama.cpp)={args.threads} | n_ctx={args.ctx} | "
                f"temperature={args.temperature} | max_tokens={args.max_tokens}")
    logger.info("[1] Concurrencia: hilos nativos dentro de cada inferencia; "
                "peticiones secuenciales (modelo del worker en producción)")
    logger.info(f"[1] Salidas: {ruta_csv.name} / {ruta_txt.name}")

    with open(BASE / "drafts_ejemplo.json") as f:
        drafts = [d["draft"] for d in json.load(f)]
    logger.info(f"[1] {len(drafts)} drafts base (se rotan cíclicamente hasta {args.inferencias} inferencias)")

    # ── [2] Montaje del grafo y prompt ───────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[2] MONTAJE DEL GRAFO Y PROMPT")
    G, alias = montar_grafo(logger)
    logger.info(f"[2] System prompt v3 ({len(SYSTEM_PROMPT_V3)} chars):\n{SYSTEM_PROMPT_V3}")
    logger.info(f"[2] Ejemplo de contexto curado (draft {drafts[0]['id']}):\n"
                f"{contexto_desde_grafo(G, alias, drafts[0])}")

    # ── [3] Montar el modelo ─────────────────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[3] MONTAJE DEL MODELO")
    ram_antes = proceso.memory_info().rss / 1e9
    t0 = time.perf_counter()
    llm = Llama(model_path=str(args.modelo), n_ctx=args.ctx, n_threads=args.threads, verbose=False)
    t_carga = time.perf_counter() - t0
    ram_modelo = proceso.memory_info().rss / 1e9 - ram_antes
    logger.info(f"[3] Modelo cargado en {t_carga:.1f} s | RAM del modelo: {ram_modelo:.2f} GB "
                f"| RAM total del proceso: {proceso.memory_info().rss / 1e9:.2f} GB")

    # ── [4] Inferencias ──────────────────────────────────────────────────────
    logger.info("═" * 70)
    logger.info(f"[4] INICIO DE {args.inferencias} INFERENCIAS")
    filas = []
    t_bench = time.perf_counter()

    for i in range(args.inferencias):
        draft = drafts[i % len(drafts)]

        t0 = time.perf_counter()
        texto_draft = draft_json_a_texto(draft)
        t_parseo = time.perf_counter() - t0

        t0 = time.perf_counter()
        contexto = contexto_desde_grafo(G, alias, draft)
        t_grafo = time.perf_counter() - t0

        mensaje = f"DRAFT DE LA PROPIEDAD:\n{texto_draft}\n\n{contexto}"

        t0 = time.perf_counter()
        salida = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_V3},
                {"role": "user", "content": mensaje},
            ],
            response_format={"type": "json_object", "schema": ESQUEMA_ANUNCIO},
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        t_llm = time.perf_counter() - t0

        t0 = time.perf_counter()
        anuncio = json.loads(salida["choices"][0]["message"]["content"])
        texto_anuncio = f"{anuncio.get('titulo', '')} {anuncio.get('descripcion', '')}"
        t_salida = time.perf_counter() - t0

        uso = salida["usage"]
        fila = {
            "inferencia": i + 1,
            "draft_id": draft["id"],
            "titulo": anuncio.get("titulo"),
            "descripcion": anuncio.get("descripcion"),
            "tokens_prompt": uso["prompt_tokens"],
            "tokens_salida": uso["completion_tokens"],
            "tokens_total": uso["total_tokens"],
            "tok_s_generacion": round(uso["completion_tokens"] / t_llm, 1),
            "t_parseo_ms": round(t_parseo * 1000, 2),
            "t_grafo_ms": round(t_grafo * 1000, 2),
            "t_llm_s": round(t_llm, 2),
            "t_salida_ms": round(t_salida * 1000, 2),
            "t_total_s": round(t_parseo + t_grafo + t_llm + t_salida, 2),
            "n_palabras": len(anuncio.get("descripcion", "").split()),
            "menciona_precio": bool(RE_PRECIO.search(texto_anuncio)),
            "menciona_contacto": bool(RE_CONTACTO.search(texto_anuncio)),
            "ram_gb": round(proceso.memory_info().rss / 1e9, 2),
        }
        filas.append(fila)
        logger.info(f"[4] {i + 1:3d}/{args.inferencias} {draft['id']} | "
                    f"parseo {fila['t_parseo_ms']:.1f} ms | grafo {fila['t_grafo_ms']:.1f} ms | "
                    f"llm {fila['t_llm_s']:.1f} s ({fila['tok_s_generacion']} tok/s) | "
                    f"prompt {fila['tokens_prompt']} tok | salida {fila['tokens_salida']} tok | "
                    f"RAM {fila['ram_gb']} GB")

    t_bench = time.perf_counter() - t_bench

    # ── [5] Recolección de resultados ────────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[5] RECOLECCIÓN DE RESULTADOS")

    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)
    logger.info(f"[5] CSV escrito: {ruta_csv} ({len(filas)} filas)")

    def resumen(clave: str) -> str:
        valores = [f[clave] for f in filas]
        return (f"prom {statistics.mean(valores):.2f} | mediana {statistics.median(valores):.2f} | "
                f"min {min(valores):.2f} | max {max(valores):.2f}"
                + (f" | p95 {statistics.quantiles(valores, n=20)[18]:.2f}" if len(valores) >= 20 else ""))

    logger.info(f"[5] Tiempo total del benchmark: {t_bench / 60:.1f} min "
                f"({t_bench / len(filas):.1f} s por inferencia efectivos)")
    logger.info(f"[5] t_parseo_ms  : {resumen('t_parseo_ms')}")
    logger.info(f"[5] t_grafo_ms   : {resumen('t_grafo_ms')}")
    logger.info(f"[5] t_llm_s      : {resumen('t_llm_s')}")
    logger.info(f"[5] t_salida_ms  : {resumen('t_salida_ms')}")
    logger.info(f"[5] t_total_s    : {resumen('t_total_s')}")
    logger.info(f"[5] tokens_prompt: {resumen('tokens_prompt')}")
    logger.info(f"[5] tokens_salida: {resumen('tokens_salida')}")
    logger.info(f"[5] tok/s gen    : {resumen('tok_s_generacion')}")
    logger.info(f"[5] palabras     : {resumen('n_palabras')}")
    violaciones = sum(f["menciona_precio"] or f["menciona_contacto"] for f in filas)
    logger.info(f"[5] Violaciones precio/contacto: {violaciones}/{len(filas)}")
    logger.info(f"[5] RAM final del proceso: {proceso.memory_info().rss / 1e9:.2f} GB")
    logger.info("[5] FIN")


if __name__ == "__main__":
    main()
