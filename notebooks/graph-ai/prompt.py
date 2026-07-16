"""
Prompt Engineering: Grafo ponderado (v4) + LLM Qwen3 1.7B (no-thinking) vía llama-server

Carga primero el grafo ponderado, levanta llama-server como subproceso,
ejecuta inferencias sobre drafts y genera títulos+descripciones usando
las decisiones del grafo como contexto.

Resultados guardados en results.md con métricas de tiempo, velocidad,
tokens y RAM.

Uso:
    python prompt.py
"""

import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
import requests

from motor_inferencia import (
    cargar_dominio,
    cargar_drafts,
    inferir,
    resumen_para_llm,
)

BASE = Path(__file__).resolve().parent
DATASETS = BASE / "datasets"
MODELS_DIR = BASE / "../../models_registry/llm"
TOOLS_DIR = BASE / "tools"
RESULTS_FILE = BASE / "results.md"

# Configuración de llama-server
LLAMA_SERVER_BIN = TOOLS_DIR / "llama-b10015/llama-server"
MODELO_GGUF = MODELS_DIR / "Qwen3-1.7B-Q4_K_M.gguf"
MODELO_NOMBRE = "Qwen3-1.7B-Q4_K_M (modo no-thinking)"
LLAMA_SERVER_PORT = 8033
LLAMA_SERVER_URL = f"http://localhost:{LLAMA_SERVER_PORT}"

# System prompt para generación de anuncios (v6: el LLM solo ve las inferencias del grafo)
SYSTEM_PROMPT_V6 = """Eres un redactor inmobiliario profesional de México. Tu única base de conocimiento es el bloque de DECISIONES DE REDACCIÓN que recibirás de un propiedad inmobiliaria: no sabes nada más de ella y no debes suponer nada.

Reglas estrictas:
1. Redacta exclusivamente con la información de las DECISIONES. No inventes características, lugares, cantidades ni cualidades que no aparezcan ahí.
2. Desarrolla los temas en el orden indicado, parafraseando sus frases con naturalidad en una narrativa fluida; nada de listas ni estilo de ficha técnica.
3. Da protagonismo a las amenidades protagonistas; las secundarias intégralas en una sola mención breve.
4. No copies lenguaje de las instrucciones al anuncio: "protagonistas", "secundarias", "temas", "audiencia", "tono" o "narrativa" jamás aparecen en el texto final.
5. PROHIBIDO: precios o cifras monetarias; datos de contacto; invitaciones a llamar, escribir o visitar; lenguaje de urgencia ("aprovecha", "no te lo pierdas", "oportunidad única").
6. Título libre de máximo 10 palabras. Descripción de 21 a 70 palabras, párrafos fluidos, tono cálido y humano, sin mayúsculas sostenidas ni signos de admiración excesivos.

Responde exclusivamente con un JSON con las claves "titulo" y "descripcion"."""


class LlamaServerClient:
    """Cliente HTTP para llama-server (OpenAI-compatible)."""

    def __init__(self, server_url: str = LLAMA_SERVER_URL):
        self.server_url = server_url
        self.endpoint = f"{server_url}/v1/chat/completions"

    def health_check(self, timeout: int = 30) -> bool:
        """Verifica que el servidor esté disponible."""
        inicio = time.time()
        while time.time() - inicio < timeout:
            try:
                resp = requests.get(f"{self.server_url}/health", timeout=2)
                if resp.status_code == 200:
                    return True
            except requests.exceptions.ConnectionError:
                time.sleep(0.5)
        return False

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> dict:
        """Genera respuesta del LLM vía HTTP (modo no-thinking)."""
        inicio = time.time()

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            # Sampling recomendado por Qwen para modo no-thinking
            "temperature": temperature,
            "top_p": 0.8,
            "top_k": 20,
            "max_tokens": max_tokens,
            # Desactiva el razonamiento (thinking) en la plantilla de chat
            "chat_template_kwargs": {"enable_thinking": False},
        }

        response = requests.post(self.endpoint, json=payload, timeout=120)
        response.raise_for_status()

        tiempo = time.time() - inicio
        data = response.json()
        texto = data["choices"][0]["message"]["content"]
        usage = data["usage"]
        completion_tokens = usage["completion_tokens"]
        tokens_por_segundo = completion_tokens / tiempo if tiempo > 0 else 0.0

        return {
            "text": texto,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": completion_tokens,
            "total_tokens": usage["total_tokens"],
            "time_s": tiempo,
            "tokens_por_segundo": tokens_por_segundo,
        }


class MemoryMonitor:
    """Monitora RAM del proceso."""

    def __init__(self):
        self.proceso = psutil.Process()
        self.inicial: Optional[float] = None
        self.maxima: float = 0.0
        self.final: Optional[float] = None

    def inicio(self):
        self.inicial = self.proceso.memory_info().rss / 1024 / 1024
        self.maxima = self.inicial

    def update(self):
        actual = self.proceso.memory_info().rss / 1024 / 1024
        self.maxima = max(self.maxima, actual)

    def fin(self):
        self.final = self.proceso.memory_info().rss / 1024 / 1024

    def consumo(self) -> dict:
        return {
            "inicial_mb": round(self.inicial or 0, 2),
            "maxima_mb": round(self.maxima, 2),
            "final_mb": round(self.final or 0, 2),
            "neto_mb": round((self.final or 0) - (self.inicial or 0), 2),
        }


def parsear_json_respuesta(texto: str) -> dict:
    """Extrae JSON de la respuesta del LLM, descartando bloques de razonamiento."""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip()
    match = re.search(r"\{.*?\}", texto, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"titulo": "ERROR", "descripcion": "No se pudo parsear la respuesta"}


def generar_para_draft(
    llm_client: LlamaServerClient,
    dominio,
    draft: dict,
    draft_idx: int,
) -> dict:
    """Ejecuta grafo + LLM para un draft."""
    print(f"\n{'='*80}")
    print(f"INFERENCIA {draft_idx + 1}: {draft.get('id')}")
    print(f"{'='*80}")

    # Metadata del draft
    draft_id = draft.get("id")
    propiedad = draft.get("propertyType", {}).get("name", "?")
    operacion = "RENTA" if draft.get("availableToRent") else "VENTA"
    area = draft.get("areaM2", "?")
    colonia = draft.get("address", {}).get("neighborhoodName", "?")

    print(f"Propiedad: {propiedad} | Operación: {operacion}")
    print(f"Área: {area}m² | Colonia: {colonia}")

    memoria = MemoryMonitor()
    tiempo_inicio = time.time()
    memoria.inicio()

    try:
        # 1. Inferencia del grafo
        decision = inferir(dominio, draft)
        resumen = resumen_para_llm(dominio, draft, decision)

        # 2. Llamada al LLM: solo recibe las decisiones del grafo, nunca el draft crudo
        mensaje_usuario = resumen

        resultado_llm = llm_client.generate(
            system_prompt=SYSTEM_PROMPT_V6,
            user_message=mensaje_usuario,
            temperature=1.0,
            max_tokens=512,
        )

        memoria.update()
        memoria.fin()
        tiempo_total = time.time() - tiempo_inicio

        # 3. Parsear resultado
        respuesta_json = parsear_json_respuesta(resultado_llm["text"])
        titulo = respuesta_json.get("titulo", "ERROR").strip()
        descripcion = respuesta_json.get("descripcion", "ERROR").strip()

        print(f"\nTítulo: {titulo}")
        print(f"Descripción: {descripcion}")

        # Métricas
        consumo = memoria.consumo()
        print(f"\nTiempo total: {tiempo_total:.3f}s")
        print(f"Tiempo LLM: {resultado_llm['time_s']:.3f}s")
        print(f"Velocidad: {resultado_llm['tokens_por_segundo']:.2f} tokens/s")
        print(f"Tokens (entrada): {resultado_llm['prompt_tokens']}")
        print(f"Tokens (salida): {resultado_llm['completion_tokens']}")
        print(f"Tokens (total): {resultado_llm['total_tokens']}")
        print(f"RAM: {consumo['inicial_mb']:.2f}MB -> {consumo['maxima_mb']:.2f}MB ({consumo['neto_mb']:+.2f}MB)")

        return {
            "draft_id": draft_id,
            "propiedad": propiedad,
            "operacion": operacion,
            "area_m2": area,
            "colonia": colonia,
            "temas_grafo": decision.temas,
            "audiencia_grafo": decision.audiencia,
            "amenidades_protagonistas": decision.protagonistas,
            "titulo": titulo,
            "descripcion": descripcion,
            "prompt_tokens": resultado_llm["prompt_tokens"],
            "completion_tokens": resultado_llm["completion_tokens"],
            "total_tokens": resultado_llm["total_tokens"],
            "tiempo_s": round(tiempo_total, 3),
            "llm_tiempo_s": round(resultado_llm["time_s"], 3),
            "tokens_por_segundo": round(resultado_llm["tokens_por_segundo"], 2),
            "ram_inicial_mb": consumo["inicial_mb"],
            "ram_maxima_mb": consumo["maxima_mb"],
            "ram_neto_mb": consumo["neto_mb"],
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"draft_id": draft_id, "error": str(e)}


def guardar_resultados(resultados: list[dict]):
    """Guarda resultados en results.md."""
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write("# Prompt Engineering: Resultados de Inferencias\n\n")
        f.write(f"**Fecha**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Modelo**: {MODELO_NOMBRE}\n")
        f.write(f"**Servidor**: llama-server (OpenAI-compatible API)\n\n")

        for i, res in enumerate(resultados, 1):
            if "error" in res:
                f.write(f"## Inferencia {i} - {res.get('draft_id', '?')} (ERROR)\n\n")
                f.write(f"**Error**: {res['error']}\n\n")
                continue

            f.write(f"## Inferencia {i}: {res['draft_id']}\n\n")
            f.write(f"**Propiedad**: {res['propiedad']} ({res['operacion']})\n")
            f.write(f"**Ubicación**: {res['colonia']}\n")
            f.write(f"**Área**: {res['area_m2']} m²\n\n")

            f.write("### Decisiones del Grafo (v4)\n")
            f.write(f"- **Temas**: {', '.join(res['temas_grafo'])}\n")
            f.write(f"- **Audiencia**: {res['audiencia_grafo']}\n")
            f.write(f"- **Amenidades protagonistas**: {', '.join(res['amenidades_protagonistas'])}\n\n")

            f.write("### Generación LLM\n")
            f.write(f"**Título** ({len(res['titulo'].split())} palabras):\n")
            f.write(f"> {res['titulo']}\n\n")
            f.write(f"**Descripción** ({len(res['descripcion'].split())} palabras):\n")
            f.write(f"> {res['descripcion']}\n\n")

            f.write("### Métricas\n")
            f.write(f"| Métrica | Valor |\n")
            f.write(f"|---------|-------|\n")
            f.write(f"| Tiempo total | {res['tiempo_s']:.3f}s |\n")
            f.write(f"| Tiempo LLM | {res['llm_tiempo_s']:.3f}s |\n")
            f.write(f"| Velocidad | {res['tokens_por_segundo']:.2f} tokens/s |\n")
            f.write(f"| Tokens entrada | {res['prompt_tokens']} |\n")
            f.write(f"| Tokens salida | {res['completion_tokens']} |\n")
            f.write(f"| Tokens total | {res['total_tokens']} |\n")
            f.write(f"| RAM inicial | {res['ram_inicial_mb']:.2f} MB |\n")
            f.write(f"| RAM máxima | {res['ram_maxima_mb']:.2f} MB |\n")
            f.write(f"| Consumo neto | {res['ram_neto_mb']:+.2f} MB |\n\n")

            f.write("---\n\n")


def main():
    """Función principal."""
    print("\n" + "="*80)
    print("PROMPT ENGINEERING: GRAFO PONDERADO + QWEN3 1.7B NO-THINKING (llama-server)")
    print("="*80)

    # Verificar archivos necesarios
    if not LLAMA_SERVER_BIN.exists():
        raise FileNotFoundError(f"llama-server no encontrado: {LLAMA_SERVER_BIN}")
    if not MODELO_GGUF.exists():
        raise FileNotFoundError(f"Modelo no encontrado: {MODELO_GGUF}")

    # 1. Cargar grafo ponderado
    print("\nCargando grafo ponderado de conocimiento...")
    tiempo_grafo = time.time()
    dominio = cargar_dominio(DATASETS)
    tiempo_grafo = time.time() - tiempo_grafo
    print(f"   Grafo cargado en {tiempo_grafo:.3f}s: {len(dominio.amenidades)} amenidades, {len(dominio.temas)} temas, {len(dominio.aristas)} aristas")

    # 2. Cargar drafts
    print("\nCargando drafts de ejemplo...")
    todos_drafts = cargar_drafts(DATASETS / "drafts_ejemplo.json")
    print(f"   {len(todos_drafts)} drafts cargados")

    # 3. Iniciar llama-server con thinking desactivado
    print(f"\nIniciando llama-server en puerto {LLAMA_SERVER_PORT}...")
    print(f"   Modelo: {MODELO_GGUF.name} (modo no-thinking)")

    tiempo_servidor = time.time()
    server_process = subprocess.Popen(
        [
            str(LLAMA_SERVER_BIN),
            "-m", str(MODELO_GGUF),
            "--port", str(LLAMA_SERVER_PORT),
            "--threads", "4",
            "--ctx-size", "4096",
            "--chat-template-kwargs", '{"enable_thinking": false}',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Esperar a que el servidor esté listo
        llm_client = LlamaServerClient(LLAMA_SERVER_URL)
        if not llm_client.health_check(timeout=30):
            raise RuntimeError("llama-server no respondió después de 30s")
        tiempo_servidor = time.time() - tiempo_servidor
        print(f"   Servidor listo en {tiempo_servidor:.3f}s")

        # 4. Inferencias
        print("\nEjecutando 3 inferencias...")
        resultados = []
        for idx, draft in enumerate(todos_drafts[:3]):
            resultado = generar_para_draft(llm_client, dominio, draft, idx)
            resultados.append(resultado)

        # 5. Guardar resultados
        print("\nGuardando resultados...")
        guardar_resultados(resultados)
        print(f"   Guardado en {RESULTS_FILE}")

        print("\n" + "="*80)
        print("COMPLETADO")
        print("="*80 + "\n")

    finally:
        # Terminar servidor
        print("\nDeteniendo llama-server...")
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
        print("   Servidor detenido")


if __name__ == "__main__":
    main()
