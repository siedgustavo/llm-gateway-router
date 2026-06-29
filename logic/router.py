from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


class RouteLabel(StrEnum):
    CODING_SIMPLE = "CODING_SIMPLE"
    SYSADMIN_OPS = "SYSADMIN_OPS"
    ARQUITECTURA_COMPLEJA = "ARQUITECTURA_COMPLEJA"


ROUTE_TO_MODEL = {
    RouteLabel.CODING_SIMPLE: "agile-coder-ops",
    RouteLabel.SYSADMIN_OPS: "agile-coder-ops",
    RouteLabel.ARQUITECTURA_COMPLEJA: "system-architect",
}


@dataclass(frozen=True)
class RouteDecision:
    label: RouteLabel
    model: str
    confidence: float
    reason: str


CLASSIFIER_SYSTEM_PROMPT = """Clasifica prompts para una plataforma local Code & Ops.
Devuelve solo JSON valido con estas claves:
{"label":"CODING_SIMPLE|SYSADMIN_OPS|ARQUITECTURA_COMPLEJA","confidence":0.0,"reason":"texto breve"}

Reglas:
- CODING_SIMPLE: editar codigo puntual, escribir funciones, tests, bugs acotados, refactors pequenos.
- SYSADMIN_OPS: bash, Linux, Docker, Kubernetes, logs, redes, systemd, GPU ops, CI/CD operativo.
- ARQUITECTURA_COMPLEJA: diseno de sistemas, migraciones grandes, refactors masivos, analisis de repos completos, algoritmos complejos, planes multi-etapa.
"""


class SemanticRouter:
    def __init__(
        self,
        client: OpenAI,
        classifier_model: str = "semantic-classifier",
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.classifier_model = classifier_model
        self.temperature = temperature

    def decide(self, prompt: str) -> RouteDecision:
        try:
            return self._classify_with_model(prompt)
        except Exception as exc:
            fallback = heuristic_route(prompt)
            return RouteDecision(
                label=fallback,
                model=ROUTE_TO_MODEL[fallback],
                confidence=0.45,
                reason=f"fallback heuristico por error del clasificador: {exc.__class__.__name__}",
            )

    @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=4), stop=stop_after_attempt(3))
    def _classify_with_model(self, prompt: str) -> RouteDecision:
        response = self.client.chat.completions.create(
            model=self.classifier_model,
            temperature=self.temperature,
            max_tokens=160,
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt[:12000]},
            ],
        )
        content = response.choices[0].message.content or ""
        payload = _extract_json(content)
        label = RouteLabel(payload["label"])
        confidence = float(payload.get("confidence", 0.7))
        reason = str(payload.get("reason", "clasificacion semantica local"))
        return RouteDecision(
            label=label,
            model=ROUTE_TO_MODEL[label],
            confidence=max(0.0, min(confidence, 1.0)),
            reason=reason[:500],
        )


def _extract_json(text: str) -> dict[str, object]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"clasificador no devolvio JSON: {text[:200]}")
    data = json.loads(match.group(0))
    if data.get("label") not in {label.value for label in RouteLabel}:
        raise ValueError(f"label invalido: {data.get('label')!r}")
    return data


def heuristic_route(prompt: str) -> RouteLabel:
    text = prompt.lower()
    if _contains_any(
        text,
        (
            "kubernetes",
            "kubectl",
            "docker",
            "compose",
            "systemd",
            "journalctl",
            "nginx",
            "traefik",
            "iptables",
            "nftables",
            "ssh",
            "ansible",
            "helm",
            "logs",
            "gpu",
            "nvidia-smi",
            "ci/cd",
            "pipeline",
            "postgres",
            "redis",
            "qdrant",
        ),
    ):
        return RouteLabel.SYSADMIN_OPS
    if _contains_any(
        text,
        (
            "arquitectura",
            "architecture",
            "diseno de sistema",
            "diseño de sistema",
            "refactor masivo",
            "migracion",
            "migración",
            "monorepo",
            "analizar todo el repo",
            "whole repository",
            "plan de rollout",
            "algoritmo complejo",
            "distributed",
        ),
    ):
        return RouteLabel.ARQUITECTURA_COMPLEJA
    return RouteLabel.CODING_SIMPLE


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)

