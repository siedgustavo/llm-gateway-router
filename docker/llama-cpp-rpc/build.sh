#!/usr/bin/env bash
# Compila y publica ghcr.io/siedgustavo/llama-cpp-rpc:latest y :latest-cuda desde el
# ultimo tag estable de llama.cpp. Todo el build ocurre dentro de Docker (stages
# multi-stage) -- no requiere CUDA toolkit ni GPU en el host que ejecuta el build.
#
# Uso:
#   ./build.sh              # resuelve el ultimo tag estable, compila, pushea
#   ./build.sh b9860        # fuerza una version/tag/commit especifico
#   ./build.sh b9860 --no-push   # solo build local, sin pushear
set -euo pipefail
cd "$(dirname "$0")"

IMAGE_BASE="ghcr.io/siedgustavo/llama-cpp-rpc"
VERSION="${1:-}"
PUSH=1
[[ "${2:-}" == "--no-push" || "${1:-}" == "--no-push" ]] && PUSH=0

if [[ -z "$VERSION" || "$VERSION" == "--no-push" ]]; then
  echo "Resolviendo ultimo tag estable de llama.cpp..."
  VERSION=$(git -c 'versionsort.suffix=-' ls-remote --tags --sort='v:refname' \
    https://github.com/ggerganov/llama.cpp.git 'b*' | tail -1 | cut -d'/' -f3)
fi
echo "LLAMACPP_VERSION=$VERSION"

echo "=== build CPU-only (rol cliente: llama-server sin computo local) ==="
docker build -f Dockerfile \
  --build-arg LLAMACPP_VERSION="$VERSION" \
  -t "${IMAGE_BASE}:latest" \
  -t "${IMAGE_BASE}:${VERSION}" \
  .

echo "=== build CUDA (rol backend RPC: rpc-server con computo GPU) ==="
docker build -f Dockerfile.cuda \
  --build-arg LLAMACPP_VERSION="$VERSION" \
  -t "${IMAGE_BASE}:latest-cuda" \
  -t "${IMAGE_BASE}:${VERSION}-cuda" \
  .

if [[ "$PUSH" == "1" ]]; then
  echo "=== push a GHCR ==="
  docker push "${IMAGE_BASE}:latest"
  docker push "${IMAGE_BASE}:${VERSION}"
  docker push "${IMAGE_BASE}:latest-cuda"
  docker push "${IMAGE_BASE}:${VERSION}-cuda"
else
  echo "--no-push: imagenes quedaron solo locales."
fi

echo ""
echo "Listo. Para desplegar en produccion, setear en los .env correspondientes:"
echo "  LLAMACPP_SERVER_IMAGE=${IMAGE_BASE}:latest      # /opt/llamacpp-rpc/server/.env (aiworker)"
echo "  LLAMACPP_RPC_IMAGE=${IMAGE_BASE}:latest-cuda    # /opt/ia-octo-server/.env (octoserver)"
echo "IMPORTANTE: actualizar cliente y backend RPC juntos (protocolo RPC fragil entre versiones distintas)."
