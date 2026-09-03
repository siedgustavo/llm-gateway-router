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
- `gustavo@corsario.core.sied.ar`: worker agil con 2x RTX 3060, Ollama para coding y ops. (corsario es el host local donde corre Claude Code.)
- `root@aiworker.core.sied.ar`: worker arquitecto con 2x RTX 3090, Ollama para tareas complejas.

Decision operativa vigente (actualizada 2026-09-02):

- TODO el stack del gateway corre en K3s namespace `inference` y esta gestionado por **Argo CD**
  (GitOps, repo `git@github.com:siedgustavo/k8s-sied-ar.git`, clon local
  `/home/gustavo/repos/k8s-sied-ar`, paths `deployments/inference/k8s/`). Las Applications tienen
  `automated sync + selfHeal`: **nunca parchear recursos live con kubectl** porque Argo revierte.
  Cambiar config = editar el YAML en ese repo, commitear y pushear. Excepcion operational:
  `kubectl -n inference rollout restart deploy/<x>` para forzar recarga de un configmap ya
  sincronizado (LiteLLM no hot-reload el `model_list`).
- El gateway canonico es LiteLLM en `https://inference.apps.sied.ar` (Ingress del namespace
  `inference`). Su config viva es `deployments/inference/k8s/litellm-config.yaml` en el repo
  k8s-sied-ar; el `gateway/litellm-config.yaml` de este repo ya NO es la fuente canonica.
- Ollama en `octoserver.core.sied.ar:11434` sirve los modelos de las RTX 3090;
  `qwen3.8-flash-next` corre en llama.cpp dedicated en `octoserver:8091` (container `qwen38flash`).
  Los antiguos llama.cpp `:8082/:8083` y el deepseek `:8084` ya no existen.
- El clasificador local es `llama3.2:3b` en `ollama-memory:11434` (StatefulSet in-cluster), residente junto a `bge-m3`. Se invoca via `ollama_chat` con `format: json`.
- `agile-coder-ops` apunta a `qwen3-coder-next:80b` en el Ollama de octoserver.
- `system-architect` apunta a `qwen3.6:35b` en el Ollama de octoserver.
- `qwen3.8-flash-next` (tope de gama, 262k ctx, reasoning) se publica como alias propio apuntando al llama.cpp dedicado de `octoserver:8091`.
- El antiguo stack Docker de `airouter.core.sied.ar` (LiteLLM, Qdrant, Postgres, Redis, Ollama en
  `:4000/:6333/:11434`) fue RETIRADO: ese host ya no resuelve DNS ni responde. Memoria, Qdrant,
  Postgres, Redis y MCP viven ahora en pods del namespace `inference`
  (`memory-mcp`, `qdrant-0`, `postgres-0`, `redis-0`, `ollama-memory-0`).
- El MCP de memoria corre como deployment `memory-mcp` in-cluster y se expone por el Ingress MCP
  del namespace `inference` (`mcp-ingress.yaml`). El servidor local `mcp/memory_mcp_server.py`
  queda como herramienta de desarrollo.

Modelos virtuales previstos:

- `semantic-classifier`: clasificador local liviano.
- `agile-coder-ops`: coding, refactors chicos, tests, bash, Kubernetes, logs y ops diarios.
- `system-architect`: arquitectura, refactors masivos, analisis de repos completos y planes multi-etapa.

## Estado del repositorio

> Nota 2026-09-02: este repo conserva el codigo de los componentes (routers, callbacks, MCP,
> Dockerfiles, scripts) pero la config desplegada vive en k8s-sied-ar. `gateway/litellm-config.yaml`
> es una COPIA de referencia sincronizada manualmente con el configmap del cluster.

Estructura creada:

- `README.md`: documentacion tecnica y despliegue.
- `gateway/litellm-config.yaml`: copia de referencia del catalogo desplegado (canonico en k8s-sied-ar).
- `gateway/auto_router.py`: ruteo automatico `auto` (clasifica y elige agile-coder-ops/system-architect).
- `gateway/permission_classifier.py`: clasificador de permisos local para auto-mode de Claude Code.
- `gateway/callbacks.py`: callbacks de LiteLLM (sanitizador de requests, redirector a permission-classifier, traffic logger).
- `gateway/Dockerfile.*`: imagenes propias de litellm, auto-router y permission-classifier (build con `scripts/build-images.sh`).
- `gateway/searxng/settings.yml`: config de SearXNG desplegada en el namespace `inference`.
- `mcp/`: servidor MCP de memoria (stdio y SSE) + MCP SSE de SearXNG.
- `docker/llama-cpp-rpc/`: build propio de llama.cpp-rpc (fix grammar con muchas tools).
- `workers/octoserver-llamacpp/`: stack llama.cpp del host octoserver (fuera de k8s).
- `workers/aiworker-llamacpp/`, `workers/corsario-worker1/`, `workers/aiworker-worker2/`: stacks historicos de workers.
- `scripts/`: `claude-routed.sh` / `claude-routed-env.sh` (lanzar Claude Code contra el gateway),
  `analyze-traffic.py` (analisis del traffic.jsonl), `build-images.sh`.
- `logic/`: router.py, orchestrator.py, rag_manager.py (orquestador Python original, superseded por el auto-router in-cluster).
- `.claude/skills/permission-classifier-log-review/`: skill de auditoria del clasificador de permisos.

Validaciones ya corridas:

- `python3 -m py_compile logic/router.py logic/orchestrator.py`
- `docker compose -f gateway/docker-compose.yml config`
- `docker compose -f workers/corsario-worker1/docker-compose.yml config`
- `docker compose -f workers/aiworker-worker2/docker-compose.yml config`

## Relevamiento de hosts

Fecha del relevamiento: 2026-06-29.

Actualizacion 2026-07-24:

- El equipo que operaba como `aiworker.core.sied.ar` en `172.16.1.39` fue reconvertido
  por decision operativa en `gpu-worker2.k8s.sied.ar`, IP `172.16.1.15`.
- Ahora tiene 2x RTX 3060 de 12 GiB y se unio al cluster K3s como agente
  `v1.31.5+k3s1`, con labels `sied.ar/gpu=true` y
  `sied.ar/role=inference-worker-3060`.
- Kubernetes publica `2` recursos `nvidia.com/gpu`; runtime NVIDIA, plugin,
  Longhorn/iSCSI y un pod de prueba con ambas GPUs fueron validados.
- Docker, el containerd del sistema y los directorios de los stacks heredados fueron
  eliminados. K3s conserva su containerd embebido y `nvidia-container-toolkit`.
- La inferencia de las RTX 3060 fue migrada al namespace `inference`: los StatefulSets
  `llamacpp-llama31-pro` (`llama3.1:8b`) y
  `llamacpp-permission-classifier` (`qwen2.5-coder:7b`) consumen una GPU cada uno.
- Cada modelo usa un PVC `longhorn-inference` de tres replicas con
  `dataLocality: best-effort`: una replica local en `gpu-worker2` y dos remotas.
- LiteLLM consume ambos backends por Services internos y se valido inferencia end-to-end.
- `172.16.1.39` dejo de pertenecer a ese host. Las secciones historicas de
  `aiworker.core.sied.ar` mas abajo describen el estado anterior a la reconversion
  y no deben usarse como inventario vigente.

### airouter.core.sied.ar

> HISTORICO (2026-09-02): este host fue RETIRADO. Ya no resuelve DNS ni responde.
> La seccion de abajo describe el estado al relevamiento original y no debe usarse
> como inventario vigente. Los reemplazos viven en el namespace `inference` de K3s.

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

- La plataforma canonica corre en K3s, namespace `inference`, administrada por GitOps desde
  `/home/gustavo/repos/k8s-sied-ar/deployments/inference`. Todo cambio (LiteLLM, routers, MCP,
  netpol, ingress) se hace editando el YAML de ese repo y pusheando: Argo CD hace sync automatico
  con `selfHeal` y revierte cualquier `kubectl apply/edit` manual sobre los recursos live.
- No volver a instalar Docker ni containerd del sistema en `gpu-worker2`; K3s usa su
  containerd embebido. No eliminar `nvidia-container-toolkit`.
- `gpu-worker2` ejecuta exclusivamente la inferencia correspondiente a sus 2x RTX 3060.
  `llama3.1:8b` y `qwen2.5-coder:7b` se consumen mediante Services internos.
- Los GGUF usan PVC `longhorn-inference`, tres replicas y
  `dataLocality: best-effort`. Mantener el `nodeSelector`
  `sied.ar/role=inference-worker-3060` para conservar una replica local junto al lector.
- No aplicar `limits.memory` a los servidores llama.cpp de `gpu-worker2`. Mantener solo la
  reserva de memoria para scheduling y el limite de una GPU por pod; este worker dispone de
  mucha mas RAM que octoserver.
- `qwen2.5-coder:7b` es solo el backend interno de `permission-classifier-router`; no
  publicarlo como perfil de chat. El router lo consume directamente por el Service
  `llamacpp-permission-classifier`.
- `llama3.1:8b` debe recibir requests sin `tools`: con varias herramientas disponibles ese
  fine-tune llama funciones innecesariamente incluso ante saludos. Para agentes con tools
  usar `auto` o `qwen3-coder-next:80b`.
- La antigua identidad `aiworker.core.sied.ar`/`172.16.1.39` y sus stacks Docker son
  inventario historico, no un backend operativo.
- Queda pendiente incorporar un nodo con rol `inference-worker-3090` para migrar los
  modelos que requieren RTX 3090.
- Mantener secretos fuera del repositorio. Usar `.env` locales no versionados para master keys, tokens y passwords.

## Proximos pasos

1. Incorporar y etiquetar el worker con las RTX 3090.
2. Crear sus StatefulSets/PVC Longhorn y migrar los modelos grandes aun externos.
3. Revalidar el ruteo completo y retirar los endpoints externos restantes.

## Comandos utiles

Relevar vLLM en `corsario`:

```bash
ssh -o UserKnownHostsFile=/tmp/corsario_known_hosts -o StrictHostKeyChecking=accept-new gustavo@corsario.core.sied.ar 'curl -sS http://127.0.0.1:8000/v1/models'
```

Relevar el worker 3060:

```bash
ssh root@172.16.1.15 'nvidia-smi; systemctl is-active k3s-agent'
kubectl -n inference get pods -o wide
kubectl -n longhorn-system get volumes.longhorn.io
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
