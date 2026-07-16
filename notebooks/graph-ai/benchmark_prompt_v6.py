"""Benchmark del pipeline v6: grafo ponderado + Qwen3-1.7B (no-thinking) vía llama-server.

Replica la configuración exacta de prompt.py: el LLM recibe únicamente las
DECISIONES DE REDACCIÓN inferidas por el grafo (nunca el draft crudo), con el
system prompt v6, sampling temperature=1.0 / top_p=0.8 / top_k=20 y el
razonamiento (thinking) desactivado en la plantilla de chat.

Ejecuta N inferencias rotando los drafts de ejemplo y mide cada etapa del
pipeline. Resultados por inferencia -> CSV; bitácora de tiempos -> TXT.

Uso (desde notebooks/graph-ai/):
    python benchmark_prompt_v6.py                     # 100 inferencias
    python benchmark_prompt_v6.py --inferencias 5     # corrida corta de prueba
    python benchmark_prompt_v6.py --parallel 2        # 2 slots con continuous batching
"""

import argparse
import csv
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
    inferir,
    resumen_para_llm,
)
from prompt import SYSTEM_PROMPT_V6, parsear_json_respuesta

BASE = Path(__file__).resolve().parent
MODELOS = BASE / "../../models_registry/llm"
SERVER_BIN_DEFAULT = BASE / "tools/llama-b10015/llama-server"

# ═════════════════════════════════════════════════════════════════════════════
# [1] VARIABLES
# ═════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark grafo ponderado + Qwen3-1.7B no-thinking (prompt v6)")
    parser.add_argument("--inferencias", type=int, default=100)
    parser.add_argument("--threads", type=int, default=4,
                        help="hilos de llama-server para generación (default: 4)")
    parser.add_argument("--ctx", type=int, default=4096,
                        help="contexto TOTAL del servidor (se divide entre slots con --parallel)")
    parser.add_argument("--parallel", type=int, default=1,
                        help="slots de continuous batching; las peticiones se lanzan con esta misma concurrencia")
    parser.add_argument("--modelo", type=Path, default=MODELOS / "Qwen3-1.7B-Q4_K_M.gguf")
    parser.add_argument("--server-bin", type=Path, default=SERVER_BIN_DEFAULT)
    parser.add_argument("--puerto", type=int, default=8033)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    return parser.parse_args()


RE_PRECIO = re.compile(r"\$|\bprecio\b|\bmxn\b|\bpesos?\b|mensualidad|mill[oó]n|\bmonto\b", re.I)
RE_CONTACTO = re.compile(
    r"cont[aá]ct|ll[aá]m[ae]|tel[eé]fono|whatsapp|escr[ií]b[ae]|agend[ae]|vis[ií]t[ae]|"
    r"aprovecha|no te lo pierdas|[uú]ltimos d[ií]as|cita|oportunidad [uú]nica", re.I)


def contiene_cifras(texto: str) -> bool:
    """Detecta dígitos en el anuncio (excluye '24h' de amenidades como Seguridad 24h)."""
    limpio = re.sub(r"24\s*h(oras)?\b", "", texto, flags=re.I)
    return bool(re.search(r"\d", limpio))


def configurar_log(ruta_txt: Path) -> logging.Logger:
    logger = logging.getLogger("benchmark_v6")
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
    """Lanza llama-server con thinking desactivado y espera a que /health responda."""
    comando = [
        str(args.server_bin),
        "--model", str(args.modelo),
        "--ctx-size", str(args.ctx),
        "--threads", str(args.threads),
        "--parallel", str(args.parallel),
        "--host", "127.0.0.1", "--port", str(args.puerto),
        "--chat-template-kwargs", '{"enable_thinking": false}',
        "--no-webui",
    ]
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
                f"RAM del servidor: {ram:.2f} GB | slots: {args.parallel} | thinking: desactivado")
    return proceso


# ═════════════════════════════════════════════════════════════════════════════
# [4] INFERENCIA (grafo -> HTTP -> parseo)
# ═════════════════════════════════════════════════════════════════════════════

def una_inferencia(i: int, draft: dict, dominio, args) -> dict:
    t0 = time.perf_counter()
    decision = inferir(dominio, draft)
    # Igual que prompt.py: el LLM solo recibe las decisiones del grafo, nunca el draft crudo
    mensaje = resumen_para_llm(dominio, draft, decision)
    t_grafo = time.perf_counter() - t0

    t0 = time.perf_counter()
    respuesta = requests.post(
        f"http://127.0.0.1:{args.puerto}/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_V6},
                {"role": "user", "content": mensaje},
            ],
            # Misma configuración de sampling que prompt.py
            "temperature": args.temperature,
            "top_p": 0.8,
            "top_k": 20,
            "max_tokens": args.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=300,
    )
    t_llm = time.perf_counter() - t0
    respuesta.raise_for_status()
    cuerpo = respuesta.json()

    t0 = time.perf_counter()
    anuncio = parsear_json_respuesta(cuerpo["choices"][0]["message"]["content"])
    titulo = (anuncio.get("titulo") or "").strip()
    descripcion = (anuncio.get("descripcion") or "").strip()
    texto = f"{titulo} {descripcion}"
    t_parseo = time.perf_counter() - t0

    uso = cuerpo.get("usage", {})
    timings = cuerpo.get("timings", {})
    return {
        "inferencia": i + 1,
        "draft_id": draft["id"],
        "titulo": titulo,
        "descripcion": descripcion,
        "tokens_prompt": uso.get("prompt_tokens"),
        "tokens_salida": uso.get("completion_tokens"),
        "tok_s_generacion": round(timings.get("predicted_per_second", 0), 1),
        "tok_s_prompt": round(timings.get("prompt_per_second", 0), 1),
        "t_grafo_ms": round(t_grafo * 1000, 2),
        "t_llm_s": round(t_llm, 2),
        "t_parseo_ms": round(t_parseo * 1000, 2),
        "t_total_s": round(t_grafo + t_llm + t_parseo, 2),
        "n_palabras_titulo": len(titulo.split()),
        "n_palabras": len(descripcion.split()),
        "error_parseo": titulo == "ERROR",
        "contiene_cifras": contiene_cifras(texto),
        "menciona_precio": bool(RE_PRECIO.search(texto)),
        "menciona_contacto": bool(RE_CONTACTO.search(texto)),
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN — etapas [1] a [5]
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    args = parse_args()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    etiqueta = f"qwen17b_v6_par{args.parallel}"
    ruta_csv = BASE / f"benchmark_{etiqueta}_{marca}.csv"
    ruta_txt = BASE / f"benchmark_{etiqueta}_{marca}.log.txt"
    logger = configurar_log(ruta_txt)

    # ── [1] Variables ────────────────────────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[1] VARIABLES")
    logger.info(f"[1] modelo={args.modelo.name} (no-thinking) | inferencias={args.inferencias} | "
                f"threads={args.threads} | ctx={args.ctx} | parallel={args.parallel} | "
                f"temperature={args.temperature} | top_p=0.8 | top_k=20 | max_tokens={args.max_tokens}")
    logger.info(f"[1] Salidas: {ruta_csv.name} / {ruta_txt.name}")

    drafts = cargar_drafts(BASE / "datasets/drafts_ejemplo.json")
    logger.info(f"[1] {len(drafts)} drafts base (rotación cíclica hasta {args.inferencias})")

    # ── [2] Montaje del grafo y prompt ───────────────────────────────────────
    logger.info("═" * 70)
    logger.info("[2] MONTAJE DEL GRAFO PONDERADO Y PROMPT")
    t0 = time.perf_counter()
    dominio = cargar_dominio(BASE / "datasets")
    logger.info(f"[2] Dominio montado en {(time.perf_counter() - t0) * 1000:.1f} ms — "
                f"{len(dominio.amenidades)} amenidades, {len(dominio.temas)} temas, "
                f"{len(dominio.aristas)} aristas")
    logger.info(f"[2] System prompt v6 ({len(SYSTEM_PROMPT_V6)} chars):\n{SYSTEM_PROMPT_V6}")
    ejemplo = inferir(dominio, drafts[0])
    logger.info(f"[2] Ejemplo de decisiones (draft {drafts[0]['id']}):\n"
                f"{resumen_para_llm(dominio, drafts[0], ejemplo)}")

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
            return una_inferencia(i, drafts[i % len(drafts)], dominio, args)

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

    logger.info(f"[5] Tiempo total: {t_bench / 60:.1f} min -> "
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
    logger.info(f"[5] palabras desc: {resumen('n_palabras')}")
    logger.info(f"[5] palabras tit : {resumen('n_palabras_titulo')}")
    errores = sum(f["error_parseo"] for f in filas)
    cifras = sum(f["contiene_cifras"] for f in filas)
    violaciones = sum(f["menciona_precio"] or f["menciona_contacto"] for f in filas)
    fuera_rango = sum(not (21 <= f["n_palabras"] <= 70) for f in filas if not f["error_parseo"])
    logger.info(f"[5] Errores de parseo JSON: {errores}/{len(filas)}")
    logger.info(f"[5] Anuncios con cifras (regla: cero): {cifras}/{len(filas)}")
    logger.info(f"[5] Violaciones precio/contacto: {violaciones}/{len(filas)}")
    logger.info(f"[5] Descripciones fuera de rango 21-70 palabras: {fuera_rango}/{len(filas)}")
    logger.info(f"[5] RAM final del servidor: {ram_final:.2f} GB")
    logger.info("[5] FIN")


if __name__ == "__main__":
    main()
