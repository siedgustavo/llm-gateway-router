# AGENTS.md

Memoria operativa del repositorio `llm-gateway-router`.

Este archivo debe ser leido al iniciar cualquier sesion de trabajo sobre esta infraestructura. Resume el requerimiento inicial, el estado real relevado de los hosts y las reglas practicas para operar sin romper servicios existentes.

## Requerimiento inicial

Construir una plataforma local/offline de ruteo de LLMs para tareas de Code & Ops dentro del dominio `*.core.sied.ar`.

Objetivos:

- Gateway central OpenAI-compatible basado en LiteLLM.
- Ruteo semantico entre coding simple, sysadmin/ops y arquitectura compleja.
- Persistencia de memoria de largo plazo con `mem0`.
- RAG/vector store local con Qdrant.
- Workers fisicos especializados por capacidad GPU.
- Sin dependencia de APIs externas en tiempo de ejecucion.

Topologia objetivo original:

- `root@airouter.core.sied.ar`: gateway, LiteLLM, Qdrant, DB de mem0, clasificador liviano `Qwen3-Coder-1.7B-Instruct`.
- `gustavo@corsario.core.sied.ar`: worker agil con 2x RTX 3060, vLLM para coding y ops.
- `root@aiworker.core.sied.ar`: worker arquitecto con 2x RTX 3090, vLLM TP=2 para tareas complejas. Tambien existe Ollama instalado y activo.

Decision operativa vigente:

- En `airouter`, la RTX A2000 de 6GB no sostiene `Qwen/Qwen3-1.7B` con vLLM 0.23.0: carga pesos pero falla por OOM durante warmup/cudagraph.
- El clasificador local estable queda en `Qwen/Qwen3-0.6B`, servido como `semantic-classifier`, con `--max-model-len 1024`, `--max-num-seqs 4`, `--max-num-batched-tokens 1024`, `--gpu-memory-utilization 0.45` y `--enforce-eager`.
- `system-architect` apunta al Ollama existente de `aiworker.core.sied.ar:11434` con `llama3.3:70b-instruct-q3_K_M`, no al puerto vLLM `8000`.
- La memoria canonica no debe usar Qdrant de `aiworker`. El vector store de memoria vive en `airouter.core.sied.ar:6333`.
- Claude Code MCP `mem0` fue reconfigurado en `/home/gustavo/.claude.json` para ejecutar `python3 /home/gustavo/repos/llm-gateway-router/mcp/memory_mcp_server.py`.
- El MCP propio usa Qdrant de `airouter:6333` y Ollama de `airouter:11434`; ya no depende del repo externo `elvismdev/mem0-mcp-selfhosted`.
- `airouter` tambien corre `llm-gateway-ollama-memory` en `:11434` para embeddings de memoria MCP. No usar Ollama de `aiworker` para memoria nueva.

Modelos virtuales previstos:

- `semantic-classifier`: clasificador local liviano.
- `agile-coder-ops`: coding, refactors chicos, tests, bash, Kubernetes, logs y ops diarios.
- `system-architect`: arquitectura, refactors masivos, analisis de repos completos y planes multi-etapa.

## Estado del repositorio

Estructura creada:

- `README.md`: documentacion tecnica y despliegue.
- `gateway/docker-compose.yml`: LiteLLM, Qdrant, Postgres, Redis y clasificador vLLM.
- `gateway/litellm-config.yaml`: modelos virtuales y ruteo local.
- `workers/corsario-worker1/docker-compose.yml`: vLLM previsto para worker agil.
- `workers/aiworker-worker2/docker-compose.yml`: vLLM previsto para worker arquitecto TP=2.
- `logic/router.py`: clasificador semantico con fallback heuristico.
- `logic/orchestrator.py`: orquestador con memoria, RAG y delegacion de modelo.
- `logic/requirements.txt`: dependencias Python.

Validaciones ya corridas:

- `python3 -m py_compile logic/router.py logic/orchestrator.py`
- `docker compose -f gateway/docker-compose.yml config`
- `docker compose -f workers/corsario-worker1/docker-compose.yml config`
- `docker compose -f workers/aiworker-worker2/docker-compose.yml config`

## Relevamiento de hosts

Fecha del relevamiento: 2026-06-29.

### airouter.core.sied.ar

Acceso:

- Usuario: `root`
- Host: `airouter.core.sied.ar`
- IP relevada: `172.16.1.38/24`

Sistema:

- AlmaLinux 9.8.
- Kernel `5.14.0-687.17.1.el9_8.x86_64`.
- VMware VM.
- 4 vCPU.
- 16 GiB RAM.
- Disco root 99G, usado 2.8G, libre 96G.

Docker:

- Docker `29.6.1`.
- Docker Compose `v5.2.0`.
- Docker activo.
- Runtime `nvidia` configurado con `nvidia-ctk`.
- Contenedores activos desde esta sesion:
  - `llm-gateway-litellm` en `:4000`.
  - `llm-gateway-qdrant` en `:6333-6334`.
  - `llm-gateway-postgres` en `:5432`.
  - `llm-gateway-redis` en `:6379`.
  - `llm-gateway-semantic-classifier` en `:8000` bajo profile `gpu-local-classifier`.
  - `llm-gateway-ollama-memory` en `:11434`.

GPU:

- NVIDIA RTX A2000 visible por PCI: `13:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA106 [RTX A2000] [10de:2531]`.
- `pciutils` instalado.
- Driver NVIDIA `610.43.02` instalado desde repo CUDA RHEL9.
- `nvidia-container-toolkit` instalado.
- DKMS status: `nvidia/610.43.02, 5.14.0-687.17.1.el9_8.x86_64, x86_64: installed`.
- Secure Boot fue desactivado en firmware/VMware.
- `mokutil --sb-state`: `SecureBoot disabled`.
- `nvidia-smi` funciona en host con driver `610.43.02`.
- Docker GPU validado con `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.
- `nvidia-persistenced` activo.
- `nouveau` estaba cargando la A2000; se dejo blacklist en `/etc/modprobe.d/blacklist-nouveau.conf` y se regenero initramfs con `dracut --force`.

Firewall:

- `firewalld` deshabilitado e inactivo por pedido operativo.
- Validacion: `systemctl is-enabled firewalld` devuelve `disabled`; `systemctl is-active firewalld` devuelve `inactive`.

VMware tools:

- `open-vm-tools` instalado.
- `vmtoolsd` habilitado y activo.

Estado operativo:

- Gateway operativo en `airouter`.
- LiteLLM responde en `http://airouter.core.sied.ar:4000`.
- Qdrant, Postgres y Redis estan activos localmente.
- Qdrant de `airouter` es el backend canonico para memoria MCP/mem0 y RAG.
- Coleccion MCP creada en `airouter`: `mem0_mcp_selfhosted`, vector size `1024`, distancia `Cosine`, sparse vector `bm25`, `points_count=0` al momento de crearla.
- Coleccion mem0 del orquestador: `mem0_user_memory` cuando `logic/orchestrator.py` corre con `mem0ai`.
- Coleccion RAG del orquestador: `llm_gateway_context`.
- Ollama de memoria activo en `http://airouter.core.sied.ar:11434`.
- Modelos Ollama de memoria en `airouter`:
  - `bge-m3:latest` para embeddings, 1024 dimensiones.
  - `llama3.2:3b` para extraccion/fact extraction de mem0 MCP.
- `llm-gateway-ollama-memory` tiene GPU visible y `OLLAMA_MAX_LOADED_MODELS=1`.
- Validacion de GPU: `bge-m3` carga en Ollama usando aprox. 744 MiB VRAM, mientras `semantic-classifier` usa aprox. 2.8 GiB; quedan aprox. 2.6 GiB libres en la A2000.
- MCP propio validado con add/search real contra Qdrant + Ollama; herramientas: `memory_add`, `memory_search`, `memory_list`, `memory_delete`.
- Clasificador GPU local activo en `http://airouter.core.sied.ar:8000/v1`.
- Modelo clasificador activo: `Qwen/Qwen3-0.6B`, servido como `semantic-classifier`.
- El cache de modelos local queda en `/srv/models/huggingface`.
- `.env` remoto en `/opt/llm-gateway-router/gateway/.env` queda con `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`, `CLASSIFIER_MODEL=Qwen/Qwen3-0.6B`, `HF_HOME_HOST=/srv/models/huggingface`, `HF_HOME=/models/huggingface`, `NVIDIA_VISIBLE_DEVICES=all`.
- Preparado durante esta sesion:
  - Repo copiado a `/opt/llm-gateway-router`.
  - Directorios creados: `/srv/models/huggingface` y `/srv/wheels`.
  - `docker compose -f gateway/docker-compose.yml config` valida correctamente en el host.
  - Repos habilitados: CRB, EPEL, CUDA RHEL9.
  - Compose default ajustado para no arrancar `semantic-classifier`; ese servicio queda bajo profile `gpu-local-classifier`.
  - vLLM `vllm/vllm-openai:latest` descargado.
  - `Qwen/Qwen3-0.6B` y `Qwen/Qwen3-1.7B` quedaron cacheados; usar 0.6B para servicio estable en A2000.

Validaciones:

- `GET /v1/models` con `Authorization: Bearer sk-local-gateway-router` lista:
  - `agile-coder-ops`
  - `system-architect`
  - `semantic-classifier`
- `agile-coder-ops` genera respuesta via `corsario.core.sied.ar:8000`.
- `system-architect` genera respuesta via Ollama en `aiworker.core.sied.ar:11434`.
- `GET http://127.0.0.1:8000/v1/models` lista `semantic-classifier` con root `Qwen/Qwen3-0.6B` y `max_model_len=1024`.
- Perfil anterior `gpu_memory_utilization=0.82` reservaba aprox. 5.4 GiB VRAM y 30k tokens de KV cache, demasiado para clasificacion. Perfil actual usa aprox. 2.8 GiB VRAM, 1.34 GiB KV cache y 12.5k tokens de KV cache.
- `semantic-classifier` genera respuesta via LiteLLM en `airouter:4000`; prueba de prompt de logs nginx devolvio `[SYSADMIN_OPS]`.
- `GET http://127.0.0.1:6333/collections` devuelve `status=ok`.
- `redis-cli ping` devuelve `PONG`.
- `pg_isready -U litellm -d litellm` acepta conexiones.

### corsario.core.sied.ar

Acceso:

- Usuario: `gustavo`
- Host: `corsario.core.sied.ar`
- La clave SSH del host requirio aceptacion aislada con `UserKnownHostsFile=/tmp/corsario_known_hosts`.

Sistema:

- AlmaLinux 10.2.
- Kernel `6.12.0-211.26.1.el10_2.x86_64`.
- CPU Intel Core i7-7700K.
- 8 threads, 4 cores.
- 30 GiB RAM.
- Swap 15 GiB.
- Disco root 476G, usado 400G, libre 77G, 85% uso.

Docker:

- Docker `29.6.0`.
- Docker Compose `v5.2.0`.
- Docker activo.

GPU:

- 2x NVIDIA GeForce RTX 3060, 12288 MiB cada una.
- Driver NVIDIA `610.43.02`.

Contenedores relevantes:

- `vllm-fast`: `vllm/vllm-openai:latest`, activo en `0.0.0.0:8000`.
- Modelo servido por `vllm-fast`: `llama3.1-fast`.
- Root real del modelo: `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4`.
- Args vLLM relevados:
  - `--served-model-name llama3.1-fast`
  - `--quantization awq`
  - `--tensor-parallel-size 2`
  - `--max-model-len 98304`
  - `--gpu-memory-utilization 0.90`
  - `--host 0.0.0.0`
  - `--port 8000`

Uso GPU actual:

- `VLLM::Worker_TP0`: aprox. 11040 MiB.
- `VLLM::Worker_TP1`: aprox. 11040 MiB.
- Las dos RTX 3060 estan practicamente ocupadas por `vllm-fast`.

Otros contenedores activos:

- `firefly-app-1` en `:8080`.
- `firefly-db-1` en `:5432`.
- Stack de monitoring con Prometheus/Grafana/Alertmanager.
- `octofan-grafana` en `:13000`.
- `octofan-prometheus` en `:19090`.

Riesgos:

- No pisar el puerto `8000` sin migrar o apagar `vllm-fast`.
- No usar `5432` para otro Postgres en este host.
- Disco alto: limpiar imagenes viejas antes de bajar modelos grandes.
- Hay tokens en env de contenedores existentes; no copiar secretos a commits ni documentacion.

### aiworker.core.sied.ar

Acceso:

- Usuario: `root`
- Host: `aiworker.core.sied.ar`
- IP usada por LiteLLM actual: `172.16.1.39`.

Sistema:

- AlmaLinux 9.7.
- Kernel `5.14.0-611.42.1.el9_7.x86_64`.
- CPU Intel Core i5-7400.
- 4 cores.
- 30 GiB RAM.
- Swap 15 GiB.
- Disco root 476G, usado 269G, libre 207G.

Docker:

- Docker `29.3.1`.
- Docker Compose `v5.1.1`.
- Docker activo.

GPU:

- 2x NVIDIA GeForce RTX 3090, 24576 MiB cada una.
- Driver NVIDIA `610.43.02`.

Contenedores relevantes:

- `claude-router`: LiteLLM `docker.litellm.ai/berriai/litellm:main-stable`, activo en `172.16.1.39:4000`.
- `qdrant`: `qdrant/qdrant:latest`, activo en `0.0.0.0:6333-6334`.
- `ollama`: `ollama/ollama:latest`, activo en `0.0.0.0:11434`.
- `claude-router-db`: `postgres:16-alpine`, interno al proyecto `claude-litellm-router`.

Compose existentes:

- `/opt/claude-litellm-router/docker-compose.yml`
- `/opt/claude-litellm-router/litellm-config.yaml`
- `/opt/qdrant/docker-compose.yml`
- `/opt/ollama/docker-compose.yml`

LiteLLM existente:

- Proyecto Compose: `claude-litellm-router`.
- Config orientada a Claude Code local router.
- Usa alias Anthropic/Claude y alias locales.
- `qwen-fast` y aliases Haiku apuntan a `corsario` via vLLM.
- `qwen-worker` y aliases Sonnet apuntan a Ollama en `aiworker`.
- El endpoint `/v1/models` requiere token valido; no se pudo listar sin la master key real.

Ollama:

- Contenedor activo y sirviendo.
- Modelo cargado actualmente:
  - `llama3.3:70b-instruct-q3_K_M`
  - 46 GB en proceso
  - 100% GPU
  - contexto 65536
  - `keep_alive` efectivo: Forever
- Uso GPU actual:
  - RTX 3090 #0 aprox. 22712 MiB.
  - RTX 3090 #1 aprox. 22340 MiB.

Memoria MCP/mem0 historica en aiworker:

- Existe un Qdrant en `aiworker:6333` con coleccion `mem0_mcp_selfhosted` y memorias viejas.
- No usarlo como backend nuevo de memoria para este proyecto.
- No migrar esas memorias automaticamente: mantener separacion para evitar mezclar estado historico con el router nuevo.
- No apagar Qdrant de `aiworker` sin confirmacion explicita; puede estar referenciado por otros flujos antiguos.

Modelos Ollama disponibles:

- `llama3.3:70b-instruct-q3_K_M`
- `llama3.1-fast:latest`
- `qwen3.6-40b-davidad-q4km:latest`
- `devstral-agentic:24b-q4`
- `devstral-small-2:24b-instruct-2512-q4_K_M`
- `llama3.3:70b-instruct-q4_K_M`
- `devstral:latest`
- `bge-m3:latest`
- `nomic-embed-text:latest`
- `qwen3.6-uncensored:latest`
- `qwen3-coder:30b`
- `llama3.1:8b`

Riesgos:

- Las dos RTX 3090 estan ocupadas por Ollama.
- Levantar vLLM TP=2 en `:8000` puede requerir liberar memoria GPU.
- Qdrant ya existe en este host, pero no se debe usar para la memoria canonica del router.
- Ya hay LiteLLM en `:4000`; no crear otro en el mismo puerto sin plan de migracion.

## Decisiones operativas actuales

- No destruir ni reiniciar contenedores existentes sin confirmacion explicita.
- Tratar `aiworker` como host con servicios productivos ya activos.
- Tratar `corsario` como worker vLLM existente, pero su modelo real actual es `llama3.1-fast`, no `Qwen/Qwen3-Coder-14B-Instruct`.
- Tratar `airouter` como gateway canonical ya activo para LiteLLM/Qdrant/Postgres/Redis.
- Tratar `airouter` como memoria canonical para MCP/mem0. No apuntar clientes nuevos al Qdrant de `aiworker`.
- La GPU de `airouter` esta operativa y el `semantic-classifier` local esta activo.
- Mantener secretos fuera del repositorio. Usar `.env` locales no versionados para master keys, tokens y passwords.

## Plan recomendado de puesta a punto

1. Corregir `airouter`.
   - Completado: Secure Boot desactivado, driver NVIDIA cargado, Docker GPU validado, firewall deshabilitado, `open-vm-tools` activo.
   - Completado: `semantic-classifier` local con profile `gpu-local-classifier`.

2. Decidir convivencia con servicios existentes.
   - `aiworker` ya corre LiteLLM/Qdrant/Ollama; no usar su Qdrant para memoria nueva.
   - Si `airouter` pasa a ser gateway canonical, migrar config de `claude-router` o exponer compatibilidad.
   - Si se mantiene `aiworker` como router temporal, actualizar este repo para reflejar la realidad.

3. Normalizar workers.
   - En `corsario`, decidir si se reemplaza `llama3.1-fast` por `Qwen/Qwen3-Coder-14B-Instruct` o si se registra `llama3.1-fast` como backend temporal de `agile-coder-ops`.
   - En `aiworker`, decidir ventana horaria para liberar Ollama y probar vLLM TP=2.

4. Activar memoria/RAG.
   - Usar exclusivamente Qdrant en `airouter`.
   - Definir colecciones:
     - `llm_gateway_context` para RAG.
     - `mem0_user_memory` para memoria de usuario.
     - `mem0_mcp_selfhosted` para memoria MCP compatible con `mem0-mcp-selfhosted`.
   - Completado: embeddings/extraccion de mem0 MCP tambien corren en `airouter` via `llm-gateway-ollama-memory`.

5. Validar end-to-end.
   - `/v1/models` de cada backend.
   - Clasificacion semantica.
   - RAG con documento de prueba.
   - Memoria mem0 con preferencia simple.
   - Delegacion `CODING_SIMPLE`/`SYSADMIN_OPS` a worker agil.
   - Delegacion `ARQUITECTURA_COMPLEJA` a worker arquitecto.

## Comandos utiles

Relevar vLLM en `corsario`:

```bash
ssh -o UserKnownHostsFile=/tmp/corsario_known_hosts -o StrictHostKeyChecking=accept-new gustavo@corsario.core.sied.ar 'curl -sS http://127.0.0.1:8000/v1/models'
```

Relevar Ollama en `aiworker`:

```bash
ssh root@aiworker.core.sied.ar 'docker exec ollama ollama ps && docker exec ollama ollama list'
```

Relevar GPU:

```bash
ssh gustavo@corsario.core.sied.ar 'nvidia-smi'
ssh root@aiworker.core.sied.ar 'nvidia-smi'
ssh root@airouter.core.sied.ar 'nvidia-smi || ls -l /dev/nvidia*'
```

Validar Compose local del repo:

```bash
docker compose -f gateway/docker-compose.yml config
docker compose -f workers/corsario-worker1/docker-compose.yml config
docker compose -f workers/aiworker-worker2/docker-compose.yml config
```

## Pendientes inmediatos

- Decidir si se conserva `vllm-fast` en `corsario` o se reemplaza por Qwen Coder.
- Incorporar `.env.example` sin secretos para cada compose.
- Ajustar `logic/orchestrator.py` si se decide usar embeddings Ollama (`bge-m3`/`nomic-embed-text`) en lugar del endpoint OpenAI-compatible esperado.
