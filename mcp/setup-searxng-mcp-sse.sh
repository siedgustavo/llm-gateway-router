#!/usr/bin/env sh
# Register the llm-gateway-router searxng MCP server in Claude Code using SSE transport.
# SSE Server runs persistently on airouter.core.sied.ar:8086
set -eu

claude mcp add --scope user --transport sse searxng http://airouter.core.sied.ar:8086/sse

echo ""
echo "MCP status:"
claude mcp list
