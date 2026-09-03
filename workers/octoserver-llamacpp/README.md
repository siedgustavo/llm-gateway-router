# octoserver-llamacpp

Arquitectura v5 (2026-07-03): `llama.cpp` corre **directo en `octoserver.core.sied.ar`**, que
tiene las 4 GPUs físicamente conectadas (2x RTX 3090 24GB + 2x RTX 3060 12GB). Reemplaza el
split RPC anterior (`aiworker` como cliente `llama-server` + `octoserver` como backend
`rpc-server`), dado de baja porque agregaba complejidad y dos bugs propios del RPC
(`state_seq_get_data` sobre RPC, ver historial en memoria del proyecto).

Arquitectura v6 (2026-07-05): `qwen3coder` y `llama31-8b` migrados a vLLM (kernels Marlin +
prefix caching, ~22x más rápido en prefill). Se probaron ademas reemplazos uncensored del coder
via vLLM+GGUF, llama.cpp y Ollama — todos descartados (ver memoria del proyecto).

**Arquitectura v7 (2026-07-06): vuelta a llama.cpp puro, un contenedor por GPU.** Se dio de baja
vLLM otra vez (mismos motivos que en el pasado: rigidez con GGUF/uncensored) y se descartó
también el intento intermedio con Ollama (bug de `finish_reason` en streaming del provider
`ollama_chat` de LiteLLM, y el modelo de reemplazo probado ahí —`gemma-4-abliterated`— no tenía
fine-tune de código). Los tres servicios corren la imagen
`ghcr.io/ggml-org/llama.cpp:server-cuda` **sin pin de versión** (build actual `b9879`): el bug de
CUDA en MoE que forzaba pinear a `b8857` (`MUL_MAT_ID failed`, `ggml-org/llama.cpp#24937`) no se
reprodujo con el mismo modelo abliterated en este build — confirmado con varios requests
secuenciales reales sin crash.

## Por qué `--no-mmap`

`octoserver` tiene solo **7.4GB de RAM**. Antes esto no importaba porque solo corría el relay
liviano de `rpc-server`. Ahora que sirve los modelos localmente, mmapear un GGUF de hasta 18GB en
un host con tan poca RAM puede generar thrashing de page cache. `--no-mmap` fuerza lectura
directa sin depender de que el archivo completo quede cacheado en RAM del host — el fundamento
central de este rediseño, y sigue aplicando en la v7 aunque ya no haya vLLM.

## Mapeo GPU → modelo

| GPU | Hardware | Modelo | Puerto | Ctx | Motor |
|-----|----------|--------|--------|-----|--------|
| 0 | RTX 3090 24GB | qwen3coder (abliterated GGUF, coder/ops) | 8080 | 65536 | llama.cpp `:server-cuda` |
| 1 | RTX 3090 24GB | qwen3.6-uncensored (GGUF, general) | 8081 | 65536 | llama.cpp `:server-cuda` |
| 2 | RTX 3060 12GB | llama31-pro (fine-tune comunitario, chatbots) | 8082 | 8192 | llama.cpp `:server-cuda` |
| 3 | RTX 3060 12GB | libre | — | — | — |

Un modelo por GPU (no hay layer-split ni tensor-parallel entre GPUs en la v7) — por eso el
contexto quedó en 65536 y no en los 128K/256K que se llegaron a probar repartiendo un modelo en
las dos 3090. Si hace falta más contexto para algún rol, la palanca es volver a repartir ese
modelo puntual en 2 GPUs, no subir el default global.

`qwen36-uncensored` necesita `LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking":false}'` para
que no mande el bloque de razonamiento (`reasoning_content`) a los clientes — el nombre de la env
var sigue la convención `LLAMA_ARG_<FLAG_EN_MAYUSCULAS>` de llama.cpp (confirmado con
`llama-server --help`); `LLAMA_CHAT_TEMPLATE_KWARGS` sin el `ARG_` se ignora en silencio.

## Deploy

Este compose vive vendorizado acá como referencia; el canónico corre en
`/opt/ia-octo-server/docker-compose.yml` en `octoserver` (junto al stack de monitoreo
`octofan-*`/Prometheus/Grafana, que no se tocó). Modelos GGUF en `/opt/llamacpp/models/`.

Variables en `/opt/ia-octo-server/.env` (host): `QWEN3CODER_*`, `QWEN36_UNCENSORED_*`,
`LLAMA31_PRO_*`, `MODELS_DIR` (alias, GGUF, ctx-size, GPU device, batch/ubatch). Reinicio por
servicio: `docker compose up -d --force-recreate <servicio>`.

## Reemplaza a

- `workers/aiworker-llamacpp/docker-compose.yml` (deprecated — `aiworker.core.sied.ar` ya no
  sirve modelos).
- Los 4 servicios `llamacpp-rpc-gpuN` (rpc-server) que antes vivían en este mismo compose.
- Los servicios `vllm-qwen3coder`/`vllm-llama31-8b` de la v6 (vLLM dado de baja de nuevo).
