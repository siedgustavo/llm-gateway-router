"""
Auto-router OpenAI-compatible para el gateway llm-gateway-router.

Expone un unico modelo virtual `auto` que:
  1. toma el ultimo mensaje del usuario,
  2. lo clasifica via el modelo `semantic-classifier` del gateway,
  3. reenvia la peticion (streaming y tools incluidos) al modelo destino:
       CODING_SIMPLE / SYSADMIN_OPS  -> agile-coder-ops (coder en corsario)
       ARQUITECTURA_COMPLEJA / GENERALISTA -> system-architect (qwen3.6 en aiworker)

Asi Claude Code u OpenCode pueden elegir un modelo fijo (agile-coder-ops /
system-architect) o `auto` para que el clasificador decida.
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
    "CODING_SIMPLE": "agile-coder-ops",       # qwen3-coder-next:80b (octoserver)
    "SYSADMIN_OPS": "agile-coder-ops",
    "ARQUITECTURA_COMPLEJA": "system-architect",  # qwen3.6:35b (octoserver)
    "GENERALISTA": "system-architect",
}

CLASSIFIER_SYSTEM_PROMPT = """Clasifica el texto en UNA categoria. Puede ser un pedido del
usuario o texto del asistente narrando/debuggeando una tarea en curso -- clasifica igual,
no hace falta que sea una orden literal.

Devuelve solo JSON valido con estas claves:
{"label":"CODING_SIMPLE|SYSADMIN_OPS|ARQUITECTURA_COMPLEJA|GENERALISTA","confidence":0.0,"reason":"texto breve"}

Reglas (elegi la mas especifica que aplique). Ante la duda entre una categoria tecnica y
GENERALISTA, elegi SIEMPRE la tecnica -- GENERALISTA es el ultimo recurso, no el default:

- CODING_SIMPLE: hay que escribir o editar codigo: funciones, tests, bugs acotados,
  refactors pequenos.
- SYSADMIN_OPS: CUALQUIER cosa relacionada a operar infraestructura o sistemas, aunque el
  texto sea una explicacion/narracion/debugging en vez de un comando literal. Incluye (no
  limitado a): bash, Linux, Docker, contenedores, pods, deployments, namespaces, secrets,
  Kubernetes/kubectl, logs, redes, DNS, firewall, systemd, journalctl, cronjobs, SSH, GPU
  ops, CUDA, VRAM, CI/CD. Si menciona pods, containers, kubectl, namespaces, deployments o
  similares, ES SYSADMIN_OPS aunque la frase suene como explicacion en vez de comando.
- ARQUITECTURA_COMPLEJA: diseno de sistemas, migraciones grandes, refactors masivos, analisis de repos completos, algoritmos complejos, planes multi-etapa.
- GENERALISTA: SOLO cuando ninguna de las anteriores aplica. Conocimiento general,
  explicaciones NO tecnicas, definiciones, redaccion, traduccion, conversacion casual,
  titulos/resumenes. NO se usa para nada que mencione infraestructura, servidores,
  contenedores o codigo, aunque sea de forma indirecta.

Ejemplos:
- "The app container is already running, so the env vars are set. Let me check the init container pod spec" -> SYSADMIN_OPS (menciona container/pod/init container: debugging de infra)
- "escribi una funcion que sume dos numeros" -> CODING_SIMPLE
- "necesito migrar todo el backend de REST a GraphQL" -> ARQUITECTURA_COMPLEJA
- "que dia es hoy" -> GENERALISTA
"""

app = FastAPI(title="llm-gateway auto-router")

_LABEL_RE = re.compile(r'"label"\s*:\s*"([A-Z_]+)"')


def _extract_text(content) -> str:
    """Texto plano de un content OpenAI/Anthropic: string, o lista de bloques
    text/tool_result (el resultado de una tool tambien puede traer texto util,
    ej. output de kubectl/comandos, que es buena senal para clasificar)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                parts.append(part.get("text", ""))
            elif ptype == "tool_result":
                parts.append(_extract_text(part.get("content", "")))
        return " ".join(p for p in parts if p)
    return ""


_BOILERPLATE_MARKERS = (
    "<system-reminder>",
    "Your previous response had no visible output",
)


def _is_boilerplate(text: str) -> bool:
    return any(marker in text for marker in _BOILERPLATE_MARKERS)


def _last_meaningful_text(messages: list[dict], role: str) -> str:
    for msg in reversed(messages):
        if msg.get("role") != role:
            continue
        text = _extract_text(msg.get("content", "")).strip()
        if text and not _is_boilerplate(text):
            return text[:12000]
    return ""


def _last_user_text(messages: list[dict]) -> str:
    """Ultimo texto representativo de lo que esta pasando en la tarea ahora.

    Orden de preferencia:
    1. Ultimo mensaje 'user' con texto real (no vacio, no boilerplate tipo
       <system-reminder>/reinyeccion de CLAUDE.md/nudges de "continua").
    2. Si no hay ninguno, ultimo mensaje 'assistant' con texto -- narra que esta
       haciendo ahora ("Secret updated, now let me force recreate the pods...") y
       es mucho mas representativo de la tarea real que esos reminders genericos.
    3. Si tampoco hay, string vacio (el llamador cae al DEFAULT_MODEL).

    En una conversacion agentica larga la mayoria de los turnos 'user' son
    tool_results sin texto plano o reinyecciones de contexto -- ninguno refleja
    que esta pasando realmente. Sin este fallback, el clasificador terminaba
    viendo boilerplate identico turno tras turno (y Redis cacheaba esa
    clasificacion mala, porque el input se repetia igual).
    """
    text = _last_meaningful_text(messages, "user")
    if text:
        return text
    return _last_meaningful_text(messages, "assistant")


async def _classify(client: httpx.AsyncClient, prompt: str, has_tools: bool = False) -> str:
    """Devuelve el model destino segun el clasificador (con fallback al default).

    Ambos destinos (coder y general) hacen tool calling bien, asi que no hay modelo
    'flojo' al que evitar; has_tools se conserva por compatibilidad de firma.
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
            return ROUTE_TO_MODEL.get(match.group(1), DEFAULT_MODEL)
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
