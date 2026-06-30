#!/usr/bin/env sh
# Exporta el entorno para correr Claude Code ruteado por el gateway llm-gateway-router.
# Agente principal -> Sonnet REAL (Anthropic via OAuth); Haiku y subagentes -> 'auto'
# (clasificador local que rutea a qwen3-coder:30b / qwen3.6:35b on-premise).
set -eu

script_path="${BASH_SOURCE:-$0}"
if command -v readlink >/dev/null 2>&1; then
  resolved_path="$(readlink -f "$script_path" 2>/dev/null || printf '%s\n' "$script_path")"
else
  resolved_path="$script_path"
fi
script_dir="$(CDPATH= cd -- "$(dirname -- "$resolved_path")" && pwd -P)"
project_dir="${CLAUDE_ROUTER_DIR:-$(CDPATH= cd -- "$script_dir/.." && pwd -P)}"

# .env opcional (gateway/.env local o deploy en /opt). Si no existe, se usa el default
# del compose (LITELLM_MASTER_KEY=sk-local-gateway-router).
env_file=""
if [ -f "$project_dir/gateway/.env" ]; then
  env_file="$project_dir/gateway/.env"
elif [ -f "/opt/llm-gateway-router/gateway/.env" ]; then
  env_file="/opt/llm-gateway-router/gateway/.env"
fi
if [ -n "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

: "${LITELLM_MASTER_KEY:=sk-local-gateway-router}"

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Advertencia: ANTHROPIC_API_KEY esta seteado. Este router usa OAuth/subscription de Claude Code, no API key. Ejecuta sin esa variable." >&2
fi
if [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  echo "Advertencia: ANTHROPIC_AUTH_TOKEN esta seteado. El router espera que Claude Code maneje OAuth sin tokens exportados." >&2
fi

# Gateway central llm-gateway-router (airouter). Override con CLAUDE_ROUTER_GATEWAY.
export ANTHROPIC_BASE_URL="${CLAUDE_ROUTER_GATEWAY:-http://airouter.core.sied.ar:4000}"
export ANTHROPIC_CUSTOM_HEADERS="x-litellm-api-key: Bearer ${LITELLM_MASTER_KEY}"

# Tiers -> nombres de modelo reales del gateway.
export ANTHROPIC_DEFAULT_SONNET_MODEL="claude-sonnet-4-6"   # principal: Sonnet REAL
export ANTHROPIC_DEFAULT_OPUS_MODEL="claude-opus-4-8"       # disponible si se elige a mano
export ANTHROPIC_DEFAULT_HAIKU_MODEL="auto"                 # local via clasificador
export CLAUDE_CODE_SUBAGENT_MODEL="auto"                    # local via clasificador (clave del ahorro)
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY="1"
export API_TIMEOUT_MS="1200000"
export BASH_DEFAULT_TIMEOUT_MS="300000"
export CLAUDE_ROUTER_DIR="$project_dir"
