# MCP servers

Two independent MCP servers run persistently as Docker containers on the gateway
(`airouter.core.sied.ar`), both in `gateway/docker-compose.yml`.

## Memory (`mem0`)

The canonical memory store for `llm-gateway-router` is Qdrant on `airouter.core.sied.ar:6333`.

There are two ways to run the memory MCP server:

### 1. Centralized SSE API (Recommended)

- **Service Port:** `8085`
- **SSE Endpoint:** `http://airouter.core.sied.ar:8085/sse`
- **Internal backend routing:** Routes directly to Qdrant and Ollama inside the `ai-core` docker network.

To register this persistent memory endpoint in Claude Code, run:

```bash
sh mcp/setup-mem0-mcp-sse.sh
```

This eliminates the need to run local python scripts on every worker machine or keep local python environments matching dependencies.

### 2. Stdio Subprocess (Legacy/Fallback)

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

### Collection Details
Target collection on airouter:
- Name: `mem0_mcp_selfhosted`
- Dense vector size: `1024`
- Distance: `Cosine`
- Sparse vector: `bm25`

### Exposed Tools
- `memory_add`
- `memory_search`
- `memory_list`
- `memory_delete`

## Web search (`searxng`)

Self-hosted [SearXNG](https://github.com/searxng/searxng) (`searxng/searxng:latest`) plus a
thin SSE MCP wrapper around its JSON search API (`mcp/searxng_mcp_server_sse.py`), both running
on the gateway (`airouter.core.sied.ar`).

- **SearXNG UI/API:** `http://airouter.core.sied.ar:8888` (config: `gateway/searxng/settings.yml`
  — `search.formats` includes `json`, required for the MCP to query it; disabled by default
  upstream for security, since a public instance shouldn't expose scraping-friendly JSON).
- **MCP SSE Endpoint:** `http://airouter.core.sied.ar:8086/sse`

To register in Claude Code:

```bash
sh mcp/setup-searxng-mcp-sse.sh
```

To register in OpenCode, add to `opencode.json`:

```json
"mcp": {
  "searxng": {
    "type": "remote",
    "url": "http://airouter.core.sied.ar:8086/sse",
    "enabled": true
  }
}
```

### Exposed Tools
- `web_search` — `query` (required), `limit` (1-20, default 5), `category` (SearXNG category,
  e.g. `general`/`news`/`images`/`it`/`science`), `language` (e.g. `es`, `en`).

### Shared Dockerfile

`mcp/Dockerfile` builds either MCP server via the `SERVER_FILE` build arg (defaults to
`memory_mcp_server_sse.py`); `gateway/docker-compose.yml`'s `searxng-mcp` service overrides it
to `searxng_mcp_server_sse.py`. One image, one Dockerfile, no duplication.
