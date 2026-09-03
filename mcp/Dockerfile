FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir mcp starlette uvicorn

# SERVER_FILE selects which MCP server this image runs (memory_mcp_server_sse.py by
# default, searxng_mcp_server_sse.py for the search MCP) -- one Dockerfile, one image
# build per service in docker-compose via `args: SERVER_FILE: ...`.
ARG SERVER_FILE=memory_mcp_server_sse.py
COPY ${SERVER_FILE} /app/server.py

EXPOSE 8085

CMD ["python", "server.py"]
