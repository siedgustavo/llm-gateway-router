# llm-gateway-router

Infraestructura local para ruteo semantico de modelos de lenguaje orientada a desarrollo de software, operaciones y diseno de arquitectura. El sistema corre dentro del dominio interno `*.core.sied.ar`, sin dependencia de proveedores externos en tiempo de ejecucion.

## Topologia fisica

| Nodo | Hostname | Hardware | Rol |
| --- | --- | --- | --- |
| Gateway | `root@airouter.core.sied.ar` | NVIDIA RTX A2000 6GB | LiteLLM, clasificador semantico local, Qdrant, PostgreSQL para memoria, Redis y orquestacion Python |
| Worker 1 | `gustavo@corsario.core.sied.ar` | 2x NVIDIA RTX 3060 12GB | vLLM para coding, refactors acotados, tests, bash, Kubernetes y lectura de logs |
| Worker 2 | `root@aiworker.core.sied.ar` | 2x NVIDIA RTX 3090 24GB | Ollama/vLLM para arquitectura, algoritmos complejos y analisis de repositorios completos |

## Modelos virtuales

LiteLLM expone tres nombres estables:

| Modelo virtual | Backend | Uso |
| --- | --- | --- |
| `semantic-classifier` | `airouter.core.sied.ar:8000` | Clasificacion de intencion entre coding simple, sysadmin y arquitectura compleja. En la A2000 usa `Qwen/Qwen3-0.6B` con contexto 1024. |
| `agile-coder-ops` | `corsario.core.sied.ar:8000` | Implementacion diaria, correcciones, pruebas, comandos operativos y diagnostico |
| `system-architect` | `aiworker.core.sied.ar:11434` | Diseno de sistemas, planes de migracion, refactors masivos y decisiones de arquitectura |

## Puertos

| Servicio | Host | Puerto |
| --- | --- | --- |
| LiteLLM Gateway | `airouter.core.sied.ar` | `4000` |
| vLLM clasificador | `airouter.core.sied.ar` | `8000` |
| Qdrant | `airouter.core.sied.ar` | `6333` |
| MCP mem0/Qdrant | `airouter.core.sied.ar` | `6333` |
| MCP mem0/Ollama | `airouter.core.sied.ar` | `11434` |
| PostgreSQL memoria | `airouter.core.sied.ar` | `5432` |
| Redis | `airouter.core.sied.ar` | `6379` |
| Worker 1 vLLM | `corsario.core.sied.ar` | `8000` |
| Worker 2 Ollama | `aiworker.core.sied.ar` | `11434` |

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

El clasificador corre como modelo local liviano en la A2000. La configuracion probada usa `Qwen/Qwen3-0.6B`, `--max-model-len 1024`, `--max-num-seqs 4`, `--max-num-batched-tokens 1024`, `--gpu-memory-utilization 0.45` y `--enforce-eager`; `Qwen/Qwen3-1.7B` no entra de forma estable en 6GB con vLLM 0.23.0. Si el clasificador no responde, el router aplica heuristicas deterministicas para preservar disponibilidad.

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
