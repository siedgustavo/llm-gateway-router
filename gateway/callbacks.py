"""
LiteLLM callbacks para el gateway llm-gateway-router.

- MaxTokensCapper.async_pre_call_hook: capa el max_tokens de salida para que los
  clientes (qwen-code manda 32000 hardcodeado) no excedan el contexto.
- TrafficLogger.async_log_success_event / async_log_failure_event: persiste cada
  request+response en JSONL para analizar despues el ruteo y afinar el clasificador.

Ambos se registran en litellm-config.yaml:
  litellm_settings:
    callbacks: ["callbacks.proxy_handler_instance", "callbacks.traffic_logger"]
"""
import json
import os
from datetime import datetime, timezone

from litellm.integrations.custom_logger import CustomLogger

MAX_OUTPUT_TOKENS = 14336

# Captura de trafico
TRAFFIC_LOG = os.environ.get("TRAFFIC_LOG", "/app/logs/traffic.jsonl")
# Truncado opcional del contenido por mensaje/respuesta (0 = sin truncar).
TRAFFIC_MAX_CHARS = int(os.environ.get("TRAFFIC_MAX_CHARS", "0"))


class MaxTokensCapper(CustomLogger):
    """Capa max_tokens antes de reenviar al backend."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get("max_tokens", 0) > MAX_OUTPUT_TOKENS:
            data["max_tokens"] = MAX_OUTPUT_TOKENS
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


proxy_handler_instance = MaxTokensCapper()
traffic_logger = TrafficLogger()
