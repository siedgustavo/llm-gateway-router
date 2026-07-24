# octoserver-llamacpp

Arquitectura v5 (2026-07-03): `llama.cpp` corre **directo en `octoserver.core.sied.ar`**, que
tiene las 4 GPUs físicamente conectadas (2x RTX 3090 24GB + 2x RTX 3060 12GB). Reemplaza el
split RPC anterior (`aiworker` como cliente `llama-server` + `octoserver` como backend
`rpc-server`), dado de baja porque agregaba complejidad y dos bugs propios del RPC
(`state_seq_get_data` sobre RPC, ver historial en memoria del proyecto).

## Por qué `--no-mmap`

`octoserver` tiene solo **7.4GB de RAM**. Antes esto no importaba porque solo corría el relay
liviano de `rpc-server`. Ahora que sirve los modelos localmente, mmapear un GGUF de hasta 18GB
en un host con tan poca RAM puede generar thrashing de page cache. `--no-mmap` fuerza lectura
directa tensor-por-tensor sin depender de que el archivo completo quede cacheado en RAM del
host — el fundamento central de este rediseño.

## Mapeo GPU → modelo

| GPU | Hardware | Modelo | Puerto | Ctx | Imagen |
|-----|----------|--------|--------|-----|--------|
| 0 | RTX 3090 24GB | qwen3coder-35b (coder/ops) | 8080 | 65536 | `:latest-cuda` |
| 1 | RTX 3090 24GB | qwen3.6-uncensored (general) | 8081 | 131072 | `:b8857-cuda` (pin CUDA MoE bug) |
| 2 | RTX 3060 12GB | llama3.1-pro (chatbots) | 8082 | 8192 | `:latest-cuda` |
| 3 | RTX 3060 12GB | libre | — | — | — |

El pin a `b8857` en GPU1 sigue siendo necesario aunque ya no haya RPC: el bug
(`ggml-org/llama.cpp#24937`) es del kernel CUDA `mul_mat_vec_q` en Ampere para modelos MoE, no
del transporte RPC.

## Deploy

Este compose vive vendorizado acá como referencia; el canónico corre en
`/opt/ia-octo-server/docker-compose.yml` en `octoserver` (junto al stack de monitoreo
`octofan-*`/Prometheus/Grafana, que no se tocó). Modelos en
`/opt/llamacpp/models/` (copiados desde `aiworker`, symlinks con los mismos nombres que usaba
`aiworker` para minimizar cambios en `.env`).

Variables en `/opt/ia-octo-server/.env` (host): `QWEN3CODER_*`, `QWEN36_UNCENSORED_*`,
`LLAMA31_PRO_*` (puertos, ctx-size, GPU device, imagen). Reinicio por servicio:
`docker compose up -d --force-recreate <servicio>`.

## Reemplaza a

- `workers/aiworker-llamacpp/docker-compose.yml` (deprecated — `aiworker.core.sied.ar` ya no
  sirve modelos).
- Los 4 servicios `llamacpp-rpc-gpuN` (rpc-server) que antes vivían en este mismo compose.
