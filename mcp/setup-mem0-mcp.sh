#!/usr/bin/env sh
# Register the llm-gateway-router memory MCP server in Claude Code.
# Canonical memory backend: Qdrant on airouter.
# Canonical extraction/embedding backend: Ollama on airouter.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

claude mcp add --scope user --transport stdio mem0 \
  --env MEMORY_QDRANT_URL=http://airouter.core.sied.ar:6333 \
  --env MEMORY_QDRANT_COLLECTION=mem0_mcp_selfhosted \
  --env MEMORY_OLLAMA_URL=http://airouter.core.sied.ar:11434 \
  --env MEMORY_EMBED_MODEL=bge-m3 \
  --env MEMORY_VECTOR_SIZE=1024 \
  --env MEMORY_USER_ID=gustavo \
  -- python3 "$SCRIPT_DIR/memory_mcp_server.py"

echo ""
echo "MCP status:"
claude mcp list
