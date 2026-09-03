# aiworker-llamacpp (DEPRECATED, 2026-07-03)

Este compose corría los 3 `llama-server` cliente (RPC contra `octoserver`). Reemplazado por
la arquitectura v5: `llama.cpp` corre directo en `octoserver.core.sied.ar` (dueño físico de
las GPUs), sin split RPC. Ver `workers/octoserver-llamacpp/README.md`.

`aiworker.core.sied.ar` deja de servir modelos. `docker-compose.yml.deprecated` queda como
referencia histórica.
