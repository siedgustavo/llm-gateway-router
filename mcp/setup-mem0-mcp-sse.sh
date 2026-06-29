#!/usr/bin/env sh
# Register the llm-gateway-router memory MCP server in Claude Code using SSE transport.
# SSE Server runs persistently on airouter.core.sied.ar:8085
set -eu

claude mcp add --scope user --transport sse mem0 http://airouter.core.sied.ar:8085/sse

echo ""
echo "MCP status:"
claude mcp list
