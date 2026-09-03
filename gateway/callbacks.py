"""
LiteLLM callbacks para el gateway llm-gateway-router.

- ProxyRequestSanitizer.async_pre_call_hook: capa el max_tokens de salida y quita
  tools de modelos publicados solo como chat.
- PermissionClassifierRedirector.async_pre_call_hook: redirige las llamadas del
  clasificador de permisos de auto-mode de Claude Code (hardcoded a un modelo real de
  Anthropic, no configurable via ANTHROPIC_DEFAULT_HAIKU_MODEL) a un modelo local, para
  no gastar cuota de suscripcion en cada chequeo de permiso durante tareas largas de
  claude-routed. Ver docstring de la clase para el detalle y la advertencia de seguridad.
- TrafficLogger.async_log_success_event / async_log_failure_event: persiste cada
  request+response en JSONL para analizar despues el ruteo y afinar el clasificador.

Se registran en litellm-config.yaml:
  litellm_settings:
    callbacks: ["callbacks.proxy_handler_instance", "callbacks.permission_classifier_redirector", "callbacks.traffic_logger"]
"""
import json
import os
from datetime import datetime, timezone

from litellm.integrations.custom_logger import CustomLogger

MAX_OUTPUT_TOKENS = 14336
NO_TOOL_MODELS = {"llama3.1:8b"}
TOOL_PARAMS = ("tools", "tool_choice", "parallel_tool_calls", "functions", "function_call")

# Captura de trafico
TRAFFIC_LOG = os.environ.get("TRAFFIC_LOG", "/app/logs/traffic.jsonl")
# Truncado opcional del contenido por mensaje/respuesta (0 = sin truncar).
TRAFFIC_MAX_CHARS = int(os.environ.get("TRAFFIC_MAX_CHARS", "0"))


class ProxyRequestSanitizer(CustomLogger):
    """Normaliza parametros antes de reenviar al backend."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get("max_tokens", 0) > MAX_OUTPUT_TOKENS:
            data["max_tokens"] = MAX_OUTPUT_TOKENS
        if data.get("model") in NO_TOOL_MODELS:
            for param in TOOL_PARAMS:
                data.pop(param, None)
        return data

    async def async_post_call_success_hook(self, *args, **kwargs):
        pass

    async def async_post_call_failure_hook(self, *args, **kwargs):
        pass

    def log_success_event(self, *args, **kwargs):
        pass

    def log_failure_event(self, *args, **kwargs):
        pass


# Texto ancla del prompt del clasificador de permisos de auto-mode de Claude Code
# (confirmado mirando gateway/logs/traffic.jsonl real: siempre llega como model=
# claude-sonnet-5/claude-opus-4-8, msgs=2, con este texto en el primer mensaje).
# Cubre las 5 variantes reales encontradas (severity fast/thinking, block fast/
# thinking, revision de lote de subagente) -- todas comparten este preambulo.
PERMISSION_CLASSIFIER_MARKER = "SPECIFIC action under review"
PERMISSION_CLASSIFIER_SOURCE_MODELS = {"claude-sonnet-5", "claude-opus-4-8"}
PERMISSION_CLASSIFIER_TARGET_MODEL = "permission-classifier"


def _looks_like_permission_classifier(messages) -> bool:
    for m in messages or []:
        content = m.get("content", "")
        if isinstance(content, list):  # formato multimodal -> texto concatenado
            content = " ".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        if isinstance(content, str) and PERMISSION_CLASSIFIER_MARKER in content:
            return True
    return False


class PermissionClassifierRedirector(CustomLogger):
    """Redirige el clasificador de permisos de auto-mode al microservicio local
    dedicado `permission-classifier` (gateway/permission_classifier.py).

    Claude Code manda esta verificacion (decide si te deja ejecutar acciones riesgosas:
    borrar archivos, git push --force, comandos destructivos, etc.) siempre a un modelo
    real de Anthropic, ignorando ANTHROPIC_DEFAULT_HAIKU_MODEL -- parece deliberado (un
    modelo no editable por el usuario para esta decision). En tareas largas de
    claude-routed dispara muchas veces por sesion y consume cuota de suscripcion.

    Historia (2026-07-19, ver memoria del proyecto para el detalle completo): 3
    intentos de redirigir DIRECTO a un modelo local fallaron -- qwen3.6:35b puntuaba
    severity ~10x mas alto que Sonnet para el mismo contenido (bloqueaba de mas,
    reportado en vivo: "no deja hacer nada al agente"), llama3.1:8b alucinaba
    categorias sin relacion con la accion real, qwen3-coder-next:80b con el prompt
    ORIGINAL de Anthropic no discriminaba nada (todo severity=3). La solucion real
    no fue "otro modelo", fue reconocer que el pipeline de Claude Code tiene 5+
    variantes distintas de este chequeo (severity/block, fast/thinking, accion unica/
    lote de subagente) y que un modelo de CODIGO con una taxonomia PROPIA de riesgo
    devops + ejemplos trabajados por categoria (no alcanza con la regla en texto
    sola) discrimina bien -- 14/14 en control sintetico Y validado contra 5
    transcripts reales completos (con y sin una accion destructiva insertada). Ver
    permission_classifier.py para el detalle de deteccion de variante, taxonomia y
    traduccion del veredicto al formato de tags exacto que cada variante espera.

    ADVERTENCIA DE SEGURIDAD (decision consciente del usuario, 2026-07): un modelo local
    es menos confiable que el Sonnet real de Anthropic para esta decision especifica --
    baja el nivel de escrutinio de la capa que aprueba acciones peligrosas. Se elige
    qwen2.5-coder:7b (no abliterated) a proposito, nunca un modelo uncensored, para no
    reemplazar el guardia de seguridad por un modelo disenado para no decir que no. Si
    el microservicio local falla o no responde, permission_classifier.py cae a
    "unsafe"/"<block>" por diseno (fail-safe, mismo comportamiento que Claude Code ya
    tiene para "classifier unavailable") -- nunca allow por default.
    """

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get("model") in PERMISSION_CLASSIFIER_SOURCE_MODELS and _looks_like_permission_classifier(
            data.get("messages")
        ):
            data["model"] = PERMISSION_CLASSIFIER_TARGET_MODEL
        return data

    async def async_post_call_success_hook(self, *args, **kwargs):
        pass

    async def async_post_call_failure_hook(self, *args, **kwargs):
        pass

    def log_success_event(self, *args, **kwargs):
        pass

    def log_failure_event(self, *args, **kwargs):
        pass


def _clip(text):
    if not isinstance(text, str):
        text = str(text)
    if TRAFFIC_MAX_CHARS and len(text) > TRAFFIC_MAX_CHARS:
        return text[:TRAFFIC_MAX_CHARS] + f"...[+{len(text) - TRAFFIC_MAX_CHARS} chars]"
    return text


def _messages_summary(messages):
    out = []
    for m in messages or []:
        content = m.get("content", "")
        if isinstance(content, list):  # formato multimodal -> texto concatenado
            content = " ".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        out.append({"role": m.get("role", "?"), "content": _clip(content)})
    return out


def _extract_response(response_obj):
    """Devuelve (texto, tool_calls, finish_reason) de un ModelResponse de LiteLLM."""
    try:
        choice = response_obj.choices[0]
        msg = getattr(choice, "message", None)
        text = getattr(msg, "content", None) if msg else None
        tool_calls = getattr(msg, "tool_calls", None) if msg else None
        tc = None
        if tool_calls:
            tc = [
                {
                    "name": getattr(t.function, "name", None),
                    "arguments": getattr(t.function, "arguments", None),
                }
                for t in tool_calls
            ]
        return (_clip(text) if text else None, tc, getattr(choice, "finish_reason", None))
    except Exception:
        return (None, None, None)


class TrafficLogger(CustomLogger):
    """Persiste cada request+response en JSONL para analisis posterior."""

    def _write(self, record):
        try:
            os.makedirs(os.path.dirname(TRAFFIC_LOG), exist_ok=True)
            with open(TRAFFIC_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # Nunca romper un request por un fallo de logging.
            pass

    def _record(self, kwargs, response_obj, start_time, end_time, status):
        text, tool_calls, finish_reason = _extract_response(response_obj)
        usage = None
        try:
            u = getattr(response_obj, "usage", None)
            if u:
                usage = {
                    "prompt_tokens": getattr(u, "prompt_tokens", None),
                    "completion_tokens": getattr(u, "completion_tokens", None),
                    "total_tokens": getattr(u, "total_tokens", None),
                }
        except Exception:
            pass
        latency_ms = None
        try:
            if start_time and end_time:
                latency_ms = round((end_time - start_time).total_seconds() * 1000)
        except Exception:
            pass
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "requested_model": kwargs.get("model"),
            "messages": _messages_summary(kwargs.get("messages")),
            "response_text": text,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "usage": usage,
            "latency_ms": latency_ms,
        }

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._write(self._record(kwargs, response_obj, start_time, end_time, "success"))

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        try:
            rec = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "status": "failure",
                "requested_model": kwargs.get("model"),
                "messages": _messages_summary(kwargs.get("messages")),
                "error": _clip(str(kwargs.get("exception", ""))),
            }
            self._write(rec)
        except Exception:
            pass


proxy_handler_instance = ProxyRequestSanitizer()
permission_classifier_redirector = PermissionClassifierRedirector()
traffic_logger = TrafficLogger()
