FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir mcp starlette uvicorn

COPY memory_mcp_server_sse.py /app/server.py

EXPOSE 8085

CMD ["python", "server.py"]
