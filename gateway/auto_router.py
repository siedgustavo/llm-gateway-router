"""
Auto-router OpenAI-compatible para el gateway llm-gateway-router.

Expone un unico modelo virtual `auto` que:
  1. toma el ultimo mensaje del usuario,
  2. lo clasifica via el modelo `semantic-classifier` del gateway,
  3. reenvia la peticion (streaming y tools incluidos) al modelo destino:
       CODING_SIMPLE / SYSADMIN_OPS  -> agile-coder-ops (coder en corsario)
       ARQUITECTURA_COMPLEJA / GENERALISTA -> system-architect (qwen3.6 en aiworker)

Asi qwen-code puede elegir un modelo fijo (agile-coder-ops / system-architect)
o `auto` para que el clasificador decida.
"""
from __future__ import annotations

import json
import os
import re

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://litellm:4000")
GATEWAY_KEY = os.environ.get("GATEWAY_KEY", "sk-local-gateway-router")
CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", "semantic-classifier")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "system-architect")

ROUTE_TO_MODEL = {
    "TRIVIAL": "llama3.1:8b",          # rapido, sin thinking (titulos, resumenes cortos)
    "CODING_SIMPLE": "agile-coder-ops",
    "SYSADMIN_OPS": "agile-coder-ops",
    "ARQUITECTURA_COMPLEJA": "system-architect",
    "GENERALISTA": "system-architect",
}

CLASSIFIER_SYSTEM_PROMPT = """Clasifica el prompt del usuario en UNA categoria.
Devuelve solo JSON valido con estas claves:
{"label":"TRIVIAL|CODING_SIMPLE|SYSADMIN_OPS|ARQUITECTURA_COMPLEJA|GENERALISTA","confidence":0.0,"reason":"texto breve"}

Reglas (elegi la mas especifica que aplique):
- TRIVIAL: tarea mecanica y corta que NO requiere razonamiento: generar un titulo, resumir en pocas palabras, dar formato, extraer un dato, clasificar/etiquetar, responder si/no. Salida breve.
- CODING_SIMPLE: hay que escribir o editar codigo: funciones, tests, bugs acotados, refactors pequenos.
- SYSADMIN_OPS: bash, Linux, Docker, Kubernetes, logs, redes, systemd, GPU ops, CI/CD operativo.
- ARQUITECTURA_COMPLEJA: diseno de sistemas, migraciones grandes, refactors masivos, analisis de repos completos, algoritmos complejos, planes multi-etapa.
- GENERALISTA: conocimiento general, explicaciones conceptuales, definiciones, redaccion larga, traduccion, conversacion. NO involucra escribir codigo ni operar infraestructura.
"""

app = FastAPI(title="llm-gateway auto-router")

_LABEL_RE = re.compile(r'"label"\s*:\s*"([A-Z_]+)"')


def _last_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):  # formato multimodal
                content = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            return str(content)[:12000]
    return ""


# Modelo con tool calling al que se redirige cuando un request CON tools cae en TRIVIAL.
# llama3.1:8b (TRIVIAL) no hace tool calling fiable -> los subagentes narran sin ejecutar.
TRIVIAL_MODEL = "llama3.1:8b"
TOOLS_FALLBACK_MODEL = "agile-coder-ops"


async def _classify(client: httpx.AsyncClient, prompt: str, has_tools: bool = False) -> str:
    """Devuelve el model destino segun el clasificador (con fallback al default).

    Si el request trae tools (p. ej. un subagente de Claude Code), nunca se rutea al
    modelo TRIVIAL: ese modelo chico no ejecuta herramientas y el agente solo narra.
    """
    try:
        resp = await client.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
            json={
                "model": CLASSIFIER_MODEL,
                "messages": [
                    {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 120,
                "temperature": 0,
                "stream": False,
            },
            timeout=40,
        )
        content = resp.json()["choices"][0]["message"].get("content") or ""
        match = _LABEL_RE.search(content)
        if match:
            target = ROUTE_TO_MODEL.get(match.group(1), DEFAULT_MODEL)
            if has_tools and target == TRIVIAL_MODEL:
                return TOOLS_FALLBACK_MODEL
            return target
    except Exception:
        pass
    return DEFAULT_MODEL


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    return JSONResponse({"object": "list", "data": [{"id": "auto", "object": "model", "owned_by": "llm-gateway"}]})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])

    has_tools = bool(body.get("tools"))
    async with httpx.AsyncClient() as client:
        target = await _classify(client, _last_user_text(messages), has_tools=has_tools)
        body["model"] = target

        headers = {"Authorization": f"Bearer {GATEWAY_KEY}", "Content-Type": "application/json"}
        url = f"{GATEWAY_URL}/v1/chat/completions"

        if body.get("stream"):
            async def proxy_stream():
                async with httpx.AsyncClient(timeout=None) as sc:
                    async with sc.stream("POST", url, headers=headers, json=body) as upstream:
                        async for chunk in upstream.aiter_raw():
                            yield chunk
            return StreamingResponse(
                proxy_stream(),
                media_type="text/event-stream",
                headers={"X-Auto-Router-Target": target},
            )

        resp = await client.post(url, headers=headers, json=body, timeout=420)
        return JSONResponse(resp.json(), headers={"X-Auto-Router-Target": target})


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
