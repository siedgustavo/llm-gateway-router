# llm-gateway-router

Infraestructura local para ruteo semantico de modelos de lenguaje orientada a desarrollo de software, operaciones y diseno de arquitectura. El sistema corre dentro del dominio interno `*.core.sied.ar`, sin dependencia de proveedores externos en tiempo de ejecucion.

## Topologia fisica

| Nodo | Hostname | Hardware | Rol |
| --- | --- | --- | --- |
| Gateway | `root@airouter.core.sied.ar` | NVIDIA RTX A2000 6GB | LiteLLM, clasificador semantico (Ollama), Qdrant, PostgreSQL para memoria, Redis y orquestacion Python |
| Worker 1 | `gustavo@corsario.core.sied.ar` | 2x NVIDIA RTX 3060 12GB | Ollama para coding, refactors acotados, tests, bash, Kubernetes y lectura de logs |
| Worker 2 | `root@aiworker.core.sied.ar` | 2x NVIDIA RTX 3090 24GB | Ollama para arquitectura, algoritmos complejos y analisis de repositorios completos |

> **Backend de inferencia: Ollama en todos los nodos.** vLLM fue retirado del proyecto (2026-06): en este hardware sin NVLink, Ollama rinde mejor (layer-split en vez de tensor-parallel), separa el razonamiento (`thinking`) del contenido, y carga modelos GGUF de cualquier arquitectura.

## Modelos virtuales

LiteLLM expone tres nombres estables (todos servidos por Ollama):

| Modelo virtual | Backend | Modelo Ollama | Uso |
| --- | --- | --- | --- |
| `semantic-classifier` | `airouter` (ollama-memory `:11434`) | `qwen3:0.6b` (`think:false`) | Clasificacion de intencion entre coding simple, sysadmin y arquitectura compleja |
| `agile-coder-ops` | `corsario.core.sied.ar:8000` | `qwen3-coder:30b` | Implementacion diaria, correcciones, pruebas, comandos operativos y diagnostico |
| `system-architect` | `aiworker.core.sied.ar:11434` | `qwen3.6:35b` | Diseno de sistemas, planes de migracion, refactors masivos, decisiones de arquitectura y consultas generalistas |
| `auto` | `airouter.core.sied.ar:4001` | (clasifica y rutea) | Ruteo automatico: clasifica el prompt y lo manda al coder o al arquitecto segun corresponda |

### Ruteo automatico (`auto`)

El servicio `auto-router` (`gateway/auto_router.py`, contenedor `llm-gateway-auto-router` en `:4001`) expone un modelo `auto` OpenAI-compatible. Por cada peticion clasifica el ultimo mensaje del usuario con `semantic-classifier` y reenvia (con streaming y tools intactos) al modelo destino. El header `X-Auto-Router-Target` informa a donde se enruto. Categorias:

| Categoria | Destino |
| --- | --- |
| `CODING_SIMPLE`, `SYSADMIN_OPS` | `agile-coder-ops` (coder en corsario) |
| `ARQUITECTURA_COMPLEJA`, `GENERALISTA` | `system-architect` (qwen3.6 en aiworker) |

En qwen-code conviven los tres: `agile-coder-ops` y `system-architect` para forzar un modelo a mano, y `auto` para dejar que el clasificador decida.

## Puertos

| Servicio | Host | Puerto |
| --- | --- | --- |
| LiteLLM Gateway | `airouter.core.sied.ar` | `4000` |
| Ollama (embeddings + clasificador) | `airouter.core.sied.ar` | `11434` |
| Qdrant | `airouter.core.sied.ar` | `6333` |
| PostgreSQL memoria | `airouter.core.sied.ar` | `5432` |
| Redis | `airouter.core.sied.ar` | `6379` |
| Worker 1 Ollama | `corsario.core.sied.ar` | `8000` (→ 11434 interno) |
| Worker 2 Ollama | `aiworker.core.sied.ar` | `11434` |

## Por que Ollama y no vLLM (decision arquitectonica)

Originalmente los workers corrian **vLLM 0.23.0**. Lo exploramos a fondo y terminamos retirandolo porque en este hardware concreto (RTX 3060/3090 **sin NVLink**, 6-48GB de VRAM, 30GB de RAM) no rendia. Esto fue lo que vivimos:

**1. Modelos que no entraban en memoria.**
- El `Qwen3-Next-80B-A3B` en AWQ pesa 49.3GB y no entra en los 48GB de las 2x3090.
- Forzarlo con `--cpu-offload-gb` (mover pesos a RAM) funciona pero **mata la velocidad**: los expertos del MoE viajan por PCIe en cada token → **~8.8 tok/s**, inusable.
- Constante pelea con OOM: tuning manual de `--kv-cache-dtype fp8`, `--max-num-batched-tokens`, `--gpu-memory-utilization` y `--enforce-eager` para que cada modelo entrara. La captura de CUDA graphs se quedaba sin VRAM una y otra vez.

**2. Tensor-parallel sin NVLink es lento para modelos densos.**
- Un denso de 27B (`Qwen3.6-27B-FP8`) con `--tensor-parallel-size 2` dio **~7 tok/s**: el all-reduce entre GPUs por cada una de las 64 capas, sobre PCIe sin NVLink, domina el tiempo. Ollama usa layer-split (pipeline) en vez de tensor-parallel y no sufre ese overhead.

**3. GGUF de arquitecturas nuevas no carga.**
- vLLM lee la config de los GGUF via `transformers`, cuyo loader GGUF solo soporta `qwen2/qwen3/qwen3_moe`. Las arquitecturas nuevas (`qwen3next`, `qwen3_5`) fallan con *"architecture not supported yet"*. Esto nos cerro la puerta a los modelos GGUF mas interesantes (incluidos los uncensored de la comunidad).

**4. El `thinking` contaminaba las respuestas.**
- Los modelos con razonamiento (Qwen3/Qwen3.6) metian el bloque `<think>...</think>` dentro del `content`, que se filtraba sucio a qwen-code.

**5. Tool calling fragil.**
- `Qwen2.5-Coder` no emitia tool calls en el formato esperado; hubo que escribir un parser custom de vLLM (`qwen25_native`) montado por volumen solo para que qwen-code pudiera ejecutar herramientas.

**Comparativa final, mismo modelo (`Qwen3.6-35B-A3B`), mismo nodo (2x3090):**

| | vLLM (FP8, TP=2) | Ollama (Q4, layer-split) |
| --- | --- | --- |
| Throughput | 66.8 tok/s | **~100 tok/s** |
| `thinking` | se filtra al `content` | campo separado, salida limpia |
| Tool calling | requiere parser custom | nativo via template |
| Modelos GGUF nuevos | no carga | carga cualquier arquitectura |
| Tuning de memoria | constante y fragil | practicamente nulo |

**Conclusion:** en hardware de consumo multi-GPU sin NVLink, Ollama (llama.cpp) rinde mejor y es mas simple de operar. vLLM brilla con NVLink y VRAM holgada (A100/H100), que no es nuestro caso. Migramos los tres nodos a Ollama el 2026-06.

## Despliegue

1. Precargar los modelos en cada nodo bajo `/srv/models/huggingface` o ajustar `HF_HOME`.
2. Crear los archivos `.env` desde los ejemplos embebidos en cada compose si se desea cambiar rutas, claves internas o tamanos.
3. Levantar cada worker en su host fisico:

```bash
cd workers/corsario-worker1
docker compose up -d

cd ../aiworker-worker2
docker compose up -d
```

4. Levantar el gateway en `airouter.core.sied.ar`:

```bash
cd gateway
docker compose up -d
```

5. Instalar la logica de orquestacion en el gateway:

```bash
cd logic
python3 -m venv .venv
. .venv/bin/activate
pip install --no-index --find-links /srv/wheels -r requirements.txt
python orchestrator.py "revisar este error de Kubernetes y proponer fix"
```

La instalacion usa `--no-index` para mantener el despliegue offline. Mantener un mirror local de wheels en `/srv/wheels` o cambiar la ruta segun la politica interna.

## Flujo de ejecucion

`logic/orchestrator.py` recibe el prompt del usuario, consulta memoria de largo plazo mediante mem0 cuando esta disponible, recupera contexto desde Qdrant y delega al modelo correcto. El ruteo operativo es:

| Categoria | Destino |
| --- | --- |
| `[CODING_SIMPLE]` | `agile-coder-ops` |
| `[SYSADMIN_OPS]` | `agile-coder-ops` |
| `[ARQUITECTURA_COMPLEJA]` | `system-architect` |

El clasificador corre como modelo local liviano (`qwen3:0.6b`) en el Ollama de `airouter` (`ollama-memory`), residente junto a `bge-m3` para embeddings (`OLLAMA_MAX_LOADED_MODELS=2`). Se invoca con `think:false` para que devuelva el JSON de clasificacion directo sin gastar tokens en razonamiento. Si el clasificador no responde, el router aplica heuristicas deterministicas para preservar disponibilidad.

## Memoria MCP

La memoria canonica vive en Qdrant sobre `airouter.core.sied.ar:6333`. No usar Qdrant de `aiworker` para clientes nuevos.

Colecciones:

| Coleccion | Uso |
| --- | --- |
| `mem0_mcp_selfhosted` | Memoria compartida por MCP `mem0-mcp-selfhosted` |
| `mem0_user_memory` | Memoria usada por `logic/orchestrator.py` via `mem0ai` |
| `llm_gateway_context` | Contexto RAG de codigo, logs y documentos |

Para registrar Claude Code contra el MCP propio del router:

```bash
sh mcp/setup-mem0-mcp.sh
```

El MCP usa `airouter` tanto para persistencia como para compute de memoria: Qdrant en `:6333`, Ollama en `:11434` y `bge-m3` para embeddings de 1024 dimensiones. El servidor MCP vive en este repo en `mcp/memory_mcp_server.py`; ya no depende del repo externo `mem0-mcp-selfhosted`.

## Operacion unificada Code & Ops

La arquitectura separa control y capacidad de computo. El gateway centraliza memoria, embeddings, RAG, auditoria y reglas de ruteo; los workers se especializan por perfil de carga. Las tareas de desarrollo y sysadmin usan el Worker 1 porque priorizan latencia, iteracion y acceso rapido a acciones concretas. Las tareas de arquitectura usan el Worker 2 porque requieren ventana de contexto, razonamiento mas largo y paralelismo de tensor.

Esta separacion permite evolucionar modelos y hardware sin cambiar la interfaz del usuario: clientes y scripts llaman siempre al gateway OpenAI-compatible de LiteLLM o al orquestador Python.
