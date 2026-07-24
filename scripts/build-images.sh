#!/usr/bin/env bash
# Construye y pushea las 5 imagenes propias del gateway a ghcr.io/siedgustavo.
# Uso:
#   scripts/build-images.sh [TAG]        # TAG por defecto: el short SHA de git + tambien :latest
#   REGISTRY=ghcr.io/otro scripts/build-images.sh v1
#
# Requiere estar logueado en el registry:  docker login ghcr.io -u siedgustavo
# Las imagenes las consume deployments/inference/k8s en el repo k8s-sied-ar.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="${REGISTRY:-ghcr.io/siedgustavo}"
TAG="${1:-$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo latest)}"

PUSH="${PUSH:-1}"   # PUSH=0 para solo buildear local

build() {
  local name="$1"; shift
  local image="${REGISTRY}/${name}"
  echo "==> build ${image}:${TAG}"
  docker build -t "${image}:${TAG}" -t "${image}:latest" "$@"
  if [[ "$PUSH" == "1" ]]; then
    echo "==> push ${image}:${TAG} + :latest"
    docker push "${image}:${TAG}"
    docker push "${image}:latest"
  fi
}

# LiteLLM (upstream + callbacks.py horneado)
build llm-gateway-litellm \
  -f "${REPO_ROOT}/gateway/Dockerfile.litellm" "${REPO_ROOT}/gateway"

# auto-router
build llm-gateway-auto-router \
  -f "${REPO_ROOT}/gateway/Dockerfile.auto-router" "${REPO_ROOT}/gateway"

# permission-classifier-router
build llm-gateway-permission-classifier \
  -f "${REPO_ROOT}/gateway/Dockerfile.permission-classifier" "${REPO_ROOT}/gateway"

# memory-mcp (mcp/Dockerfile, SERVER_FILE por defecto = memory_mcp_server_sse.py)
build llm-gateway-memory-mcp \
  -f "${REPO_ROOT}/mcp/Dockerfile" "${REPO_ROOT}/mcp"

# searxng-mcp (mismo Dockerfile, otro SERVER_FILE)
build llm-gateway-searxng-mcp \
  --build-arg SERVER_FILE=searxng_mcp_server_sse.py \
  -f "${REPO_ROOT}/mcp/Dockerfile" "${REPO_ROOT}/mcp"

echo
echo "Listo. Tag construido: ${TAG}"
echo "Para fijar el tag en k8s (recomendado sobre :latest), editar las imagenes en"
echo "deployments/inference/k8s/*.yaml de ghcr.io/siedgustavo/<img>:latest a :${TAG}."
