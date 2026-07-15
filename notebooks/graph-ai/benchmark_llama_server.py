"""Benchmark del stack de producción: llama-server + grafo ponderado (pipeline v4).

Levanta llama-server como subproceso (el runtime que usará el worker), ejecuta N inferencias
de {titulo, descripcion} vía HTTP (API OpenAI-compatible) rotando los drafts de ejemplo, y
mide cada etapa del pipeline. Resultados por inferencia → CSV; bitácora de tiempos → TXT.

Uso (desde notebooks/graph-ai/, con el venv de notebooks):
    ../.venv/bin/python benchmark_llama_server.py                     # 100 inferencias, baseline
    ../.venv/bin/python benchmark_llama_server.py --draft             # + speculative decoding (0.6B)
    ../.venv/bin/python benchmark_llama_server.py --parallel 2        # 2 slots con continuous batching
    ../.venv/bin/python benchmark_llama_server.py --inferencias 5     # corrida corta de prueba

Palancas que este benchmark compara contra el runtime en proceso (llama-cpp-python):
- --draft: el 0.6B propone tokens y el 4B los verifica EN LOTE (misma calidad, 1.5–2× esperado).
- --parallel N: continuous batching — N solicitudes comparten la lectura de pesos
  (sube el throughput de la cola; la latencia individual no baja).
"""

import argparse
import csv
import json
import logging
import os
import re
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import psutil
import requests

from motor_inferencia import (
    cargar_dominio,
    cargar_drafts,
    draft_json_a_texto,
    inferir,
    resumen_para_llm,
)

BASE = Path(__file__).resolve().parent
MODELOS = BASE / "../../models_registry/llm"
SERVER_BIN_DEFAULT = BASE / "tools/llama-b10015/llama-server"

# ═════════════════════════════════════════════════════════════════════════════
# [1] VARIABLES
# ═════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark llama-server + grafo ponderado (v4)")
    parser.add_argument("--inferencias", type=int, default=100)
    parser.add_argument("--threads", type=int, default=4,
                        help="hilos de llama-server para generación (default: 4)")
    parser.add_argument("--ctx", type=int, default=4096,
                        help="contexto TOTAL del servidor (se divide entre slots con --parallel)")
    parser.add_argument("--parallel", type=int, default=1,
                        help="slots de continuous batching; las peticiones se lanzan con esta misma concurrencia")
    parser.add_argument("--draft", action="store_true",
                        help="activa speculative decoding con el borrador Qwen3-0.6B")
    parser.add_argument("--modelo", type=Path, default=MODELOS / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")
    parser.add_argument("--modelo-draft", type=Path, default=MODELOS / "Qwen3-0.6B-Q8_0.gguf")
    parser.add_argument("--server-bin", type=Path, default=SERVER_BIN_DEFAULT)
    parser.add_argument("--puerto", type=int, default=8033)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    return parser.parse_args()


SYSTEM_PROMPT_V4 = """Eres un redactor inmobiliario profesional de México. Recibirás el DRAFT de una \
propiedad y un bloque de DECISIONES DE REDACCIÓN ya tomadas. Tu único trabajo es redactar el \
anuncio obedeciéndolas.

Reglas estrictas:
1. Escribe SOLO con la información del DRAFT y de las DECISIONES. No agregues características, \
lugares, vistas ni cualidades que no aparezcan ahí.
2. Desarrolla los temas en el orden indicado parafraseando sus frases con naturalidad. Destaca \
las amenidades protagonistas; las secundarias solo de pasada.
3. PROHIBIDO: precios o cifras monetarias; datos de contacto; invitaciones a llamar, escribir o \
visitar; lenguaje de urgencia ("aprovecha", "no te lo pierdas", "oportunidad única").
4. Ubicación: solo el nombre de la colonia. Di "recámaras" y "estacionamientos" (vocabulario \
de la región). Si el draft no menciona estacionamientos, no hables de ellos.
5. Título de máximo 10 palabras. Descripción de 21 a 70 palabras, párrafos fluidos, tono cálido \
y humano, sin mayúsculas sostenidas ni signos de admiración excesivos.

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
    logger = logging.getLogger("benchmark_server")
    logger.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    for handler in (logging.FileHandler(ruta_txt, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formato)
        logger.addHandler(handler)
    return logger


# ═════════════════════════════════════════════════════════════════════════════
# [3] MONTAJE DEL SERVIDOR
# ═════════════════════════════════════════════════════════════════════════════

def levantar_servidor(args, logger: logging.Logger) -> subprocess.Popen:
    """Lanza llama-server y espera a que el endpoint /health responda."""
    comando = [
        str(args.server_bin),
        "--model", str(args.modelo),
        "--ctx-size", str(args.ctx),
        "--threads", str(args.threads),
        "--parallel", str(args.parallel),
        "--host", "127.0.0.1", "--port", str(args.puerto),
        "--no-webui",
    ]
    if args.draft:
        comando += ["--model-draft", str(args.modelo_draft),
                    "--spec-draft-n-max", "16", "--spec-draft-n-min", "1"]
    logger.info(f"[3] Comando: {' '.join(comando)}")

    t0 = time.perf_counter()
    proceso = subprocess.Popen(
        comando,
        env={**os.environ, "LD_LIBRARY_PATH": str(args.server_bin.parent)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    salud = f"http://127.0.0.1:{args.puerto}/health"
    for _ in range(600):  # hasta 60 s de arranque
        if proceso.poll() is not None:
            raise RuntimeError(f"llama-server terminó al arrancar (código {proceso.returncode}); "
                               f"revisa la ruta del modelo y el binario")
        try:
            if requests.get(salud, timeout=1).status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(0.1)
    else:
        proceso.kill()
        raise RuntimeError("llama-server no respondió /health en 60 s")

    ram = psutil.Process(proceso.pid).memory_info().rss / 1e9
    logger.info(f"[3] llama-server listo en {time.perf_counter() - t0:.1f} s | "
                f"RAM del servidor: {ram:.2f} GB | slots: {args.parallel} | draft: {args.draft}")
    return proceso


# ═════════════════════════════════════════════════════════════════════════════
# [4] INFERENCIA (grafo → HTTP → parseo)
# ═════════════════════════════════════════════════════════════════════════════

def una_inferencia(i: int, draft: dict, dominio, args) -> dict:
    t0 = time.perf_counter()
    decision = inferir(dominio, draft)
    mensaje = (f"DRAFT DE LA PROPIEDAD:\n{draft_json_a_texto(draft)}\n\n"
               f"{resumen_para_llm(dominio, draft, decision)}")
    t_grafo = time.perf_counter() - t0

    t0 = time.perf_counter()
    respuesta = requests.post(
        f"http://127.0.0.1:{args.puerto}/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_V4},
                {"role": "user", "content": mensaje},
            ],
            "response_format": {"type": "json_object", "schema": ESQUEMA_ANUNCIO},
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
        },
        timeout=300,
    )
    t_llm = time.perf_counter() - t0
    respuesta.raise_for_status()
    cuerpo = respuesta.json()

    t0 = time.perf_counter()
    anuncio = json.loads(cuerpo["choices"][0]["message"]["content"])
    texto = f"{anuncio.get('titulo', '')} {anuncio.get('descripcion', '')}"
    t_parseo = time.perf_counter() - t0

    uso = cuerpo.get("usage", {})
    timings = cuerpo.get("timings", {})
    return {
        "inferencia": i + 1,
        "draft_id": draft["id"],
        "titulo": anuncio.get("titulo"),
        "descripcion": anuncio.get("descripcion"),
        "tokens_prompt": uso.get("prompt_tokens"),
        "tokens_salida": uso.get("completion_tokens"),
        "tok_s_generacion": round(timings.get("predicted_per_second", 0), 1),
        "tok_s_prompt": round(timings.get("prompt_per_second", 0), 1),
        "t_grafo_ms": round(t_grafo * 1000, 2),
        "t_llm_s": round(t_llm, 2),
        "t_parseo_ms": round(t_parseo * 1000, 2),
        "t_total_s": round(t_grafo + t_llm + t_parseo, 2),
        "n_palabras": len(anuncio.get("descripcion", "").split()),
        "menciona_precio": bool(RE_PRECIO.search(texto)),
        "menciona_contacto": bool(RE_CONTACTO.search(texto)),
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN — etapas [1] a [5]
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    args = parse_args()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    etiqueta = f"draft{int(args.draft)}_par{args.parallel}"
    ruta_csv = BASE / f"benchmark_server_{etiqueta}_{marca}.csv"
    ruta_txt = BASE / f"benchmark_server_{etiqueta}_{marca}.log.txt"
    logger = configurar_log(ruta_txt)

    # ── [1] Variables ────────────────────────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[1] VARIABLES")
    logger.info(f"[1] modelo={args.modelo.name} | inferencias={args.inferencias} | "
                f"threads={args.threads} | ctx={args.ctx} | parallel={args.parallel} | "
                f"draft={'sí (' + args.modelo_draft.name + ')' if args.draft else 'no'} | "
                f"temperature={args.temperature} | max_tokens={args.max_tokens}")
    logger.info("[1] Concurrencia: llama-server con continuous batching; las peticiones se "
                f"lanzan con {args.parallel} worker(s) HTTP (mismo modelo que tendrá la cola)")
    logger.info(f"[1] Salidas: {ruta_csv.name} / {ruta_txt.name}")

    dominio_drafts = cargar_drafts(BASE / "datasets/drafts_ejemplo.json")
    logger.info(f"[1] {len(dominio_drafts)} drafts base (rotación cíclica hasta {args.inferencias})")

    # ── [2] Montaje del grafo y prompt ───────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[2] MONTAJE DEL GRAFO Y PROMPT")
    t0 = time.perf_counter()
    dominio = cargar_dominio(BASE / "datasets")
    logger.info(f"[2] Dominio montado en {(time.perf_counter() - t0) * 1000:.1f} ms — "
                f"{len(dominio.amenidades)} amenidades, {len(dominio.temas)} temas, "
                f"{len(dominio.aristas)} aristas")
    logger.info(f"[2] System prompt v4 ({len(SYSTEM_PROMPT_V4)} chars):\n{SYSTEM_PROMPT_V4}")
    ejemplo = inferir(dominio, dominio_drafts[0])
    logger.info(f"[2] Ejemplo de decisiones (draft {dominio_drafts[0]['id']}):\n"
                f"{resumen_para_llm(dominio, dominio_drafts[0], ejemplo)}")

    # ── [3] Montaje del servidor ─────────────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[3] MONTAJE DEL SERVIDOR (llama-server)")
    servidor = levantar_servidor(args, logger)

    try:
        # ── [4] Inferencias ──────────────────────────────────────────────────
        logger.info("═" * 70)
        logger.info(f"[4] INICIO DE {args.inferencias} INFERENCIAS")
        t_bench = time.perf_counter()
        filas = []

        def tarea(i: int) -> dict:
            return una_inferencia(i, dominio_drafts[i % len(dominio_drafts)], dominio, args)

        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            for fila in pool.map(tarea, range(args.inferencias)):
                filas.append(fila)
                logger.info(f"[4] {fila['inferencia']:3d}/{args.inferencias} {fila['draft_id']} | "
                            f"grafo {fila['t_grafo_ms']:.1f} ms | llm {fila['t_llm_s']:.1f} s "
                            f"({fila['tok_s_generacion']} tok/s gen) | "
                            f"prompt {fila['tokens_prompt']} tok | salida {fila['tokens_salida']} tok")

        t_bench = time.perf_counter() - t_bench
        ram_final = psutil.Process(servidor.pid).memory_info().rss / 1e9
    finally:
        servidor.terminate()
        servidor.wait(timeout=10)

    # ── [5] Recolección de resultados ────────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[5] RECOLECCIÓN DE RESULTADOS")
    filas.sort(key=lambda f: f["inferencia"])
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)
    logger.info(f"[5] CSV escrito: {ruta_csv} ({len(filas)} filas)")

    def resumen(clave: str) -> str:
        valores = [f[clave] for f in filas if f[clave] is not None]
        return (f"prom {statistics.mean(valores):.2f} | mediana {statistics.median(valores):.2f} | "
                f"min {min(valores):.2f} | max {max(valores):.2f}"
                + (f" | p95 {statistics.quantiles(valores, n=20)[18]:.2f}" if len(valores) >= 20 else ""))

    logger.info(f"[5] Tiempo total: {t_bench / 60:.1f} min → "
                f"throughput {len(filas) / t_bench * 60:.1f} anuncios/min "
                f"({t_bench / len(filas):.1f} s por anuncio efectivos)")
    logger.info(f"[5] t_grafo_ms   : {resumen('t_grafo_ms')}")
    logger.info(f"[5] t_llm_s      : {resumen('t_llm_s')}")
    logger.info(f"[5] t_parseo_ms  : {resumen('t_parseo_ms')}")
    logger.info(f"[5] t_total_s    : {resumen('t_total_s')}")
    logger.info(f"[5] tokens_prompt: {resumen('tokens_prompt')}")
    logger.info(f"[5] tokens_salida: {resumen('tokens_salida')}")
    logger.info(f"[5] tok/s gen    : {resumen('tok_s_generacion')} (del timing interno del servidor)")
    logger.info(f"[5] tok/s prompt : {resumen('tok_s_prompt')}")
    logger.info(f"[5] palabras     : {resumen('n_palabras')}")
    violaciones = sum(f["menciona_precio"] or f["menciona_contacto"] for f in filas)
    logger.info(f"[5] Violaciones precio/contacto: {violaciones}/{len(filas)}")
    logger.info(f"[5] RAM final del servidor: {ram_final:.2f} GB")
    logger.info("[5] FIN")


if __name__ == "__main__":
    main()
