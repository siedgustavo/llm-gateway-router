#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib import error, request


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "llm-gateway-router-memory"
SERVER_VERSION = "0.1.0"


class Settings:
    qdrant_url = os.getenv("MEMORY_QDRANT_URL", "http://airouter.core.sied.ar:6333").rstrip("/")
    collection = os.getenv("MEMORY_QDRANT_COLLECTION", "mem0_mcp_selfhosted")
    ollama_url = os.getenv("MEMORY_OLLAMA_URL", "http://airouter.core.sied.ar:11434").rstrip("/")
    embed_model = os.getenv("MEMORY_EMBED_MODEL", "bge-m3")
    user_id = os.getenv("MEMORY_USER_ID", "gustavo")
    vector_size = int(os.getenv("MEMORY_VECTOR_SIZE", "1024"))


TOOLS = [
    {
        "name": "memory_add",
        "description": "Store a durable memory in the local airouter memory backend.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory text to store."},
                "user_id": {"type": "string", "description": "User id. Defaults to configured user."},
                "project": {"type": "string", "description": "Optional project or repo scope."},
                "metadata": {"type": "object", "description": "Optional structured metadata."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_search",
        "description": "Search durable memories by semantic similarity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "user_id": {"type": "string", "description": "User id. Defaults to configured user."},
                "project": {"type": "string", "description": "Optional project or repo scope."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_list",
        "description": "List recent durable memories for a user and optional project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User id. Defaults to configured user."},
                "project": {"type": "string", "description": "Optional project or repo scope."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
        },
    },
    {
        "name": "memory_delete",
        "description": "Delete a memory by point id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Qdrant point id returned by memory_add/list/search."},
            },
            "required": ["id"],
        },
    },
]


def main() -> int:
    ensure_collection()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle_message(message)
            if response is not None:
                write_message(response)
        except Exception as exc:
            write_message(error_response(None, -32603, f"internal error: {exc}"))
    return 0


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return result_response(
            message_id,
            {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return result_response(message_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        return result_response(message_id, call_tool(name, arguments))
    if method == "ping":
        return result_response(message_id, {})
    if message_id is None:
        return None
    return error_response(message_id, -32601, f"unknown method: {method}")


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "memory_add":
        result = memory_add(arguments)
    elif name == "memory_search":
        result = memory_search(arguments)
    elif name == "memory_list":
        result = memory_list(arguments)
    elif name == "memory_delete":
        result = memory_delete(arguments)
    else:
        return tool_error(f"unknown tool: {name}")
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}


def memory_add(arguments: dict[str, Any]) -> dict[str, Any]:
    content = required_str(arguments, "content").strip()
    if not content:
        raise ValueError("content cannot be empty")
    user_id = str(arguments.get("user_id") or Settings.user_id)
    project = arguments.get("project")
    metadata = arguments.get("metadata") if isinstance(arguments.get("metadata"), dict) else {}
    point_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "memory": content,
        "text": content,
        "user_id": user_id,
        "project": project,
        "metadata": metadata,
        "created_at": now,
        "updated_at": now,
        "source": SERVER_NAME,
    }
    vector = embed(content)
    qdrant_put(
        f"/collections/{Settings.collection}/points?wait=true",
        {"points": [{"id": point_id, "vector": vector, "payload": payload}]},
    )
    return {"id": point_id, "user_id": user_id, "project": project, "created_at": now, "memory": content}


def memory_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = required_str(arguments, "query")
    user_id = str(arguments.get("user_id") or Settings.user_id)
    project = arguments.get("project")
    limit = bounded_int(arguments.get("limit", 5), 1, 20)
    vector = embed(query)
    body: dict[str, Any] = {
        "vector": vector,
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
        "filter": qdrant_filter(user_id, project),
    }
    data = qdrant_post(f"/collections/{Settings.collection}/points/search", body)
    points = data.get("result", [])
    return {"query": query, "count": len(points), "memories": [format_point(point) for point in points]}


def memory_list(arguments: dict[str, Any]) -> dict[str, Any]:
    user_id = str(arguments.get("user_id") or Settings.user_id)
    project = arguments.get("project")
    limit = bounded_int(arguments.get("limit", 10), 1, 50)
    data = qdrant_post(
        f"/collections/{Settings.collection}/points/scroll",
        {
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
            "filter": qdrant_filter(user_id, project),
        },
    )
    points = data.get("result", {}).get("points", [])
    formatted = sorted((format_point(point) for point in points), key=lambda item: item.get("created_at") or "", reverse=True)
    return {"count": len(formatted), "memories": formatted}


def memory_delete(arguments: dict[str, Any]) -> dict[str, Any]:
    point_id = required_str(arguments, "id")
    qdrant_post(f"/collections/{Settings.collection}/points/delete?wait=true", {"points": [point_id]})
    return {"deleted": point_id}


def ensure_collection() -> None:
    try:
        qdrant_get(f"/collections/{Settings.collection}")
        return
    except RuntimeError:
        pass
    qdrant_put(
        f"/collections/{Settings.collection}",
        {
            "vectors": {"size": Settings.vector_size, "distance": "Cosine", "on_disk": False},
            "sparse_vectors": {"bm25": {"modifier": "idf"}},
            "on_disk_payload": True,
        },
    )


def embed(text: str) -> list[float]:
    data = http_json(
        f"{Settings.ollama_url}/api/embed",
        "POST",
        {"model": Settings.embed_model, "input": text},
        timeout=120,
    )
    embeddings = data.get("embeddings") or []
    if not embeddings or not isinstance(embeddings[0], list):
        raise RuntimeError(f"ollama did not return embeddings for model {Settings.embed_model}")
    vector = embeddings[0]
    if len(vector) != Settings.vector_size:
        raise RuntimeError(f"embedding size mismatch: got {len(vector)}, expected {Settings.vector_size}")
    return vector


def qdrant_filter(user_id: str, project: Any | None) -> dict[str, Any]:
    must = [{"key": "user_id", "match": {"value": user_id}}]
    if project:
        must.append({"key": "project", "match": {"value": str(project)}})
    return {"must": must}


def format_point(point: dict[str, Any]) -> dict[str, Any]:
    payload = point.get("payload") or {}
    return {
        "id": str(point.get("id")),
        "score": point.get("score"),
        "memory": payload.get("memory") or payload.get("text") or "",
        "user_id": payload.get("user_id"),
        "project": payload.get("project"),
        "metadata": payload.get("metadata") or {},
        "created_at": payload.get("created_at"),
    }


def required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} is required")
    return value


def bounded_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = minimum
    return max(minimum, min(parsed, maximum))


def qdrant_get(path: str) -> dict[str, Any]:
    return http_json(f"{Settings.qdrant_url}{path}", "GET", None)


def qdrant_put(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return http_json(f"{Settings.qdrant_url}{path}", "PUT", body)


def qdrant_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return http_json(f"{Settings.qdrant_url}{path}", "POST", body)


def http_json(url: str, method: str, body: dict[str, Any] | None, timeout: int = 30) -> dict[str, Any]:
    raw = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(url, data=raw, method=method, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc
    return json.loads(data) if data else {}


def result_response(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def error_response(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def tool_error(message: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
