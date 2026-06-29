from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.http.models import ScoredPoint
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

from router import RouteDecision, SemanticRouter

try:
    from mem0 import Memory
except Exception:
    Memory = None


console = Console(stderr=True)


class Settings(BaseModel):
    litellm_base_url: str = Field(default="http://airouter.core.sied.ar:4000/v1")
    litellm_api_key: str = Field(default="sk-local-gateway-router")
    qdrant_url: str = Field(default="http://airouter.core.sied.ar:6333")
    qdrant_collection: str = Field(default="llm_gateway_context")
    embedding_model: str = Field(default="bge-m3")
    user_id: str = Field(default="gustavo")
    memory_enabled: bool = Field(default=True)
    rag_enabled: bool = Field(default=True)
    rag_limit: int = Field(default=6)
    temperature: float = Field(default=0.2)
    max_tokens: int = Field(default=4096)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            litellm_base_url=os.getenv("LITELLM_BASE_URL", cls.model_fields["litellm_base_url"].default),
            litellm_api_key=os.getenv("LITELLM_API_KEY", cls.model_fields["litellm_api_key"].default),
            qdrant_url=os.getenv("QDRANT_URL", cls.model_fields["qdrant_url"].default),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", cls.model_fields["qdrant_collection"].default),
            embedding_model=os.getenv("EMBEDDING_MODEL", cls.model_fields["embedding_model"].default),
            user_id=os.getenv("MEM0_USER_ID", cls.model_fields["user_id"].default),
            memory_enabled=os.getenv("MEMORY_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            rag_enabled=os.getenv("RAG_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            rag_limit=int(os.getenv("RAG_LIMIT", str(cls.model_fields["rag_limit"].default))),
            temperature=float(os.getenv("GENERATION_TEMPERATURE", str(cls.model_fields["temperature"].default))),
            max_tokens=int(os.getenv("MAX_TOKENS", str(cls.model_fields["max_tokens"].default))),
        )


@dataclass
class OrchestrationContext:
    route: RouteDecision
    memories: list[str]
    rag_documents: list[str]


class LocalMemory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory: Any | None = None
        if not settings.memory_enabled:
            return
        if Memory is None:
            console.print("[yellow]mem0 no esta instalado o no cargo; continuo sin memoria persistente[/yellow]")
            return
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "url": settings.qdrant_url,
                    "collection_name": "mem0_user_memory",
                    "embedding_model_dims": 1024,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "agile-coder-ops",
                    "openai_base_url": settings.litellm_base_url,
                    "api_key": settings.litellm_api_key,
                    "temperature": 0.0,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": settings.embedding_model,
                    "openai_base_url": settings.litellm_base_url,
                    "api_key": settings.litellm_api_key,
                },
            },
        }
        self.memory = Memory.from_config(config)

    def search(self, prompt: str) -> list[str]:
        if self.memory is None:
            return []
        try:
            result = self.memory.search(prompt, user_id=self.settings.user_id, limit=5)
            return normalize_mem0_results(result)
        except Exception as exc:
            console.print(f"[yellow]mem0 search fallo: {exc}[/yellow]")
            return []

    def remember_interaction(self, prompt: str, answer: str, route: RouteDecision) -> None:
        if self.memory is None:
            return
        try:
            self.memory.add(
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": f"[{route.label.value}] {answer[:6000]}"},
                ],
                user_id=self.settings.user_id,
                metadata={"route": route.label.value, "model": route.model},
            )
        except Exception as exc:
            console.print(f"[yellow]mem0 add fallo: {exc}[/yellow]")


class RagStore:
    def __init__(self, settings: Settings, openai_client: OpenAI) -> None:
        self.settings = settings
        self.openai_client = openai_client
        self.qdrant = QdrantClient(url=settings.qdrant_url)

    def search(self, prompt: str) -> list[str]:
        if not self.settings.rag_enabled:
            return []
        try:
            embedding = self._embed(prompt)
            points = self.qdrant.search(
                collection_name=self.settings.qdrant_collection,
                query_vector=embedding,
                limit=self.settings.rag_limit,
                with_payload=True,
            )
            return [format_point(point) for point in points if point.payload]
        except Exception as exc:
            console.print(f"[yellow]RAG search fallo: {exc}[/yellow]")
            return []

    @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=4), stop=stop_after_attempt(3))
    def _embed(self, text: str) -> list[float]:
        response = self.openai_client.embeddings.create(
            model=self.settings.embedding_model,
            input=text[:16000],
        )
        return response.data[0].embedding


class FlowOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(base_url=settings.litellm_base_url, api_key=settings.litellm_api_key)
        self.router = SemanticRouter(self.client)
        self.memory = LocalMemory(settings)
        self.rag = RagStore(settings, self.client)

    def run(self, prompt: str) -> str:
        route = self.router.decide(prompt)
        memories = self.memory.search(prompt)
        documents = self.rag.search(prompt)
        context = OrchestrationContext(route=route, memories=memories, rag_documents=documents)
        answer = self._complete(prompt, context)
        self.memory.remember_interaction(prompt, answer, route)
        return answer

    @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=6), stop=stop_after_attempt(3))
    def _complete(self, prompt: str, context: OrchestrationContext) -> str:
        system_prompt = build_system_prompt(context)
        response = self.client.chat.completions.create(
            model=context.route.model,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""


def build_system_prompt(context: OrchestrationContext) -> str:
    memory_block = "\n".join(f"- {item}" for item in context.memories) or "- Sin preferencias persistentes recuperadas."
    rag_block = "\n\n".join(context.rag_documents) or "Sin documentos RAG relevantes recuperados."
    return f"""Eres un agente local Code & Ops dentro de *.core.sied.ar.
Ruta decidida: [{context.route.label.value}]
Modelo destino: {context.route.model}
Confianza: {context.route.confidence:.2f}
Motivo: {context.route.reason}

Prioridades:
- Responder con pasos accionables y comandos concretos cuando corresponda.
- Preservar operacion offline/local; no depender de SaaS externos.
- Para cambios de software, preferir modificaciones pequenas, testeables y coherentes con el repositorio.
- Para sysadmin, explicitar host objetivo, riesgo operacional y verificacion.
- Para arquitectura, separar decision, tradeoffs, plan de implementacion y rollout.

Preferencias y memoria del usuario:
{memory_block}

Contexto recuperado por RAG:
{rag_block}
"""


def normalize_mem0_results(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, dict):
        memories = result.get("results") or result.get("memories") or []
    else:
        memories = result
    normalized: list[str] = []
    for item in memories:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, dict):
            text = item.get("memory") or item.get("text") or item.get("content")
            if text:
                normalized.append(str(text))
    return normalized[:8]


def format_point(point: ScoredPoint) -> str:
    payload = point.payload or {}
    source = payload.get("source") or payload.get("path") or payload.get("file") or "origen-desconocido"
    content = payload.get("content") or payload.get("text") or payload.get("chunk") or ""
    score = "n/a" if point.score is None else f"{point.score:.4f}"
    return f"[source={source} score={score}]\n{str(content)[:6000]}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orquestador local para llm-gateway-router")
    parser.add_argument("prompt", nargs="*", help="Prompt a ejecutar. Si se omite, lee stdin.")
    parser.add_argument("--show-route", action="store_true", help="Imprime metadata de ruteo en stderr.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    prompt = " ".join(args.prompt).strip() if args.prompt else sys.stdin.read().strip()
    if not prompt:
        console.print("[red]No se recibio prompt por argumento ni stdin[/red]")
        return 2

    settings = Settings.from_env()
    orchestrator = FlowOrchestrator(settings)
    answer = orchestrator.run(prompt)
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

