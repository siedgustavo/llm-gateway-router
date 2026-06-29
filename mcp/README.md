# MCP memory

The canonical memory store for `llm-gateway-router` is Qdrant on `airouter.core.sied.ar:6333`.

There are two ways to run the memory MCP server:

## 1. Centralized SSE API (Recommended)

The memory MCP server runs persistently in a Docker container on the gateway (`airouter.core.sied.ar`):

- **Service Port:** `8085`
- **SSE Endpoint:** `http://airouter.core.sied.ar:8085/sse`
- **Internal backend routing:** Routes directly to Qdrant and Ollama inside the `ai-core` docker network.

To register this persistent memory endpoint in Claude Code, run:

```bash
sh mcp/setup-mem0-mcp-sse.sh
```

This eliminates the need to run local python scripts on every worker machine or keep local python environments matching dependencies.

## 2. Stdio Subprocess (Legacy/Fallback)

You can also run the stdio-based server locally as a subprocess:

```text
mcp/memory_mcp_server.py
```

The server stores vectors in the airouter collection `mem0_mcp_selfhosted` and uses Ollama on airouter for embeddings.

Current endpoints:
- Memory persistence: `http://airouter.core.sied.ar:6333`
- Extraction and embeddings compute: `http://airouter.core.sied.ar:11434`
- Extraction model: `llama3.2:3b`
- Embedding model: `bge-m3`
- Embedding dimensions: `1024`
- User id: `gustavo`

Do not point new clients at Qdrant on `aiworker`; that is historical state from the old Claude router setup.

To register the stdio version, run:

```bash
sh mcp/setup-mem0-mcp.sh
```

## Collection Details
Target collection on airouter:
- Name: `mem0_mcp_selfhosted`
- Dense vector size: `1024`
- Distance: `Cosine`
- Sparse vector: `bm25`

## Exposed Tools
- `memory_add`
- `memory_search`
- `memory_list`
- `memory_delete`
