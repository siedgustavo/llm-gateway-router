#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib import error, parse, request

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import Response
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server import Server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("searxng-mcp-sse")


class Settings:
    searxng_url = os.getenv("SEARXNG_URL", "http://searxng:8080").rstrip("/")


app = Server("llm-gateway-router-searxng-sse")
sse = SseServerTransport("/messages/")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="web_search",
            description="Search the web via a self-hosted SearXNG instance. Returns title/url/snippet per result.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    "category": {
                        "type": "string",
                        "description": "SearXNG category, e.g. general, news, images, it, science.",
                        "default": "general",
                    },
                    "language": {"type": "string", "description": "Language code, e.g. es, en.", "default": ""},
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    logger.info(f"Calling tool: {name} with args: {arguments}")
    try:
        if name == "web_search":
            result = web_search(arguments)
        else:
            raise ValueError(f"unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


def web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = required_str(arguments, "query")
    limit = bounded_int(arguments.get("limit", 5), 1, 20)
    category = str(arguments.get("category") or "general")
    language = str(arguments.get("language") or "")

    params = {
        "q": query,
        "format": "json",
        "categories": category,
    }
    if language:
        params["language"] = language

    url = f"{Settings.searxng_url}/search?{parse.urlencode(params)}"
    data = http_json(url, timeout=30)

    results = []
    for item in (data.get("results") or [])[:limit]:
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
                "engine": item.get("engine"),
            }
        )
    return {"query": query, "count": len(results), "results": results}


def required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required and must be a non-empty string")
    return value


def bounded_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = minimum
    return max(minimum, min(parsed, maximum))


def http_json(url: str, timeout: int = 30) -> dict[str, Any]:
    req = request.Request(url, headers={"Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc
    return json.loads(data) if data else {}


async def handle_sse(request):
    logger.info("New SSE connection requested")
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())
    return Response()


# Streamable HTTP transport (/mcp): required by clients like Open WebUI that
# dropped legacy SSE support. /sse + /messages/ stay for existing clients.
session_manager = StreamableHTTPSessionManager(app, stateless=True)

routes = [
    Route("/sse", endpoint=handle_sse, methods=["GET"]),
    Mount("/messages/", app=sse.handle_post_message),
    Mount("/mcp", app=session_manager.handle_request),
]

starlette_app = Starlette(
    routes=routes,
    lifespan=lambda _: session_manager.run(),
)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8086"))
    logger.info(f"Starting MCP SSE searxng server on port {port}, backend {Settings.searxng_url}...")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)
