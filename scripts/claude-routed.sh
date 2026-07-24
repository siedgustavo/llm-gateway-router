#!/usr/bin/env sh
# Lanza Claude Code apuntando al gateway llm-gateway-router (airouter:4000):
#   - agente principal -> Sonnet REAL (Anthropic, OAuth de Claude Code)
#   - Haiku + subagentes -> 'auto' (clasificador local, on-premise)
# No modifica ~/.claude/settings.json; solo entorno temporal de este proceso.
set -eu

script_path="$0"
if command -v readlink >/dev/null 2>&1; then
  resolved_path="$(readlink -f "$script_path" 2>/dev/null || printf '%s\n' "$script_path")"
else
  resolved_path="$script_path"
fi
script_dir="$(CDPATH= cd -- "$(dirname -- "$resolved_path")" && pwd -P)"
project_dir="$(CDPATH= cd -- "$script_dir/.." && pwd -P)"

# shellcheck disable=SC1091
. "$project_dir/scripts/claude-routed-env.sh"

if ! command -v claude >/dev/null 2>&1; then
  echo "No encontre 'claude' en PATH. Instala/carga Claude Code CLI primero." >&2
  exit 1
fi

if ! curl -fsS --max-time 5 "${ANTHROPIC_BASE_URL}/health/liveliness" >/dev/null 2>&1; then
  echo "El gateway LiteLLM no responde en ${ANTHROPIC_BASE_URL}." >&2
  echo "Verifica el stack: kubectl -n inference get pods" >&2
  exit 1
fi

echo "Claude Code routed mode:"
echo "* Gateway: ${ANTHROPIC_BASE_URL} (llm-gateway-router / k8s gpu-worker1)"
echo "* Auth: Claude Code OAuth/subscription, sin API key"
echo "* Principal (Sonnet): claude-sonnet-5 (Anthropic REAL)"
echo "* Opus (a mano):      claude-opus-4-8  (Anthropic REAL)"
echo "* Haiku + subagentes: auto -> clasificador local (qwen3-coder:30b / qwen3.6:35b)"
echo ""

exec claude "$@"
