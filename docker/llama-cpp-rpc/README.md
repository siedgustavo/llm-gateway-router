# llama.cpp RPC — build propio

Vendorizado desde [`EvilFreelancer/docker-llama.cpp-rpc`](https://github.com/EvilFreelancer/docker-llama.cpp-rpc)
porque la imagen publicada (`evilfreelancer/llama.cpp-rpc`) quedó congelada en un build
de febrero 2026 (commit `01d8eaa`) que sufre `llama_grammar_init_impl: failed to parse
grammar` cuando un cliente manda muchas tools (10+, como OpenCode o los subagentes de
Claude Code) — el grammar GBNF no compila, el modelo genera sin restricción de formato
y nunca emite un tool call valido.

Publicamos nuestro propio build en `ghcr.io/siedgustavo/llama-cpp-rpc` compilado desde
un tag reciente de llama.cpp (que ya incluye fixes upstream sobre tool-calling XML
malformado en Qwen3.6, issues `#24863`/`#24807`).

## Archivos

- `Dockerfile` — build CPU-only. Rol **cliente** (`llama-server`): no hace computo
  local, todo el trabajo pesado se delega via `--rpc` a los backends. No necesita CUDA.
- `Dockerfile.cuda` — build con CUDA. Rol **backend RPC** (`rpc-server`): hace el
  computo real en GPU.
- `entrypoint.sh` — igual al original: soporta `APP_MODE=server|backend|none` via env,
  o se puede pasar un CMD custom (asi lo usan los compose de aiworker/octoserver hoy).
- `build.sh` — script para recompilar y publicar ambas variantes.

## Diferencias vs el original

1. **`rpc-server` renombrado**: en versiones nuevas de llama.cpp el target/binario se
   llama `ggml-rpc-server`. Se copia y renombra a `rpc-server` en el `COPY` del
   Dockerfile para no tener que tocar los compose existentes (que hardcodean
   `entrypoint: ["/app/rpc-server"]` y `/app/llama-server`).
2. **Symlinks de librerias generico**: las versiones nuevas agregan mas `.so` de las
   que el proyecto original conocia (ej. `libllama-common.so`). En vez de listar los
   nombres a mano, el Dockerfile crea `libxxx.so.0 -> libxxx.so` para **todas** las
   `.so` presentes, a prueba de que upstream agregue mas librerias en el futuro.

## Uso

```bash
# Compilar y publicar desde el ultimo tag estable de llama.cpp (recomendado)
./build.sh

# Fijar una version concreta (reproducible)
./build.sh b9860

# Solo build local, sin pushear a GHCR
./build.sh b9860 --no-push
```

El build **no requiere CUDA toolkit ni GPU en el host que ejecuta `docker build`** — todo
ocurre dentro de las stages de Docker (la imagen `nvidia/cuda:*-devel` hace de compilador).

## Deploy

Los compose de produccion ya parametrizan la imagen por variable de entorno, no hace
falta editar YAML:

```bash
# aiworker: /opt/llamacpp-rpc/server/.env
LLAMACPP_SERVER_IMAGE=ghcr.io/siedgustavo/llama-cpp-rpc:latest

# octoserver: /opt/ia-octo-server/.env
LLAMACPP_RPC_IMAGE=ghcr.io/siedgustavo/llama-cpp-rpc:latest-cuda
```

**Actualizar cliente y backend RPC juntos** — el protocolo RPC de llama.cpp es fragil y
esta ligado a la version exacta; mezclar versiones distintas entre `llama-server` y
`rpc-server` puede romper la comunicacion.

Reiniciar de a un servicio por vez con `docker compose up -d --force-recreate <servicio>`,
confirmar `"server is listening"` en logs y VRAM sin OOM antes de seguir con el siguiente.

## Rollback

Si algo sale mal, volver los `.env` a los defaults (`evilfreelancer/llama.cpp-rpc:latest`
/ `:latest-cuda`) y recrear los contenedores — es la imagen que corria antes, sin cambios.
