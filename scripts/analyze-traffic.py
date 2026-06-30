#!/usr/bin/env python3
"""
Analiza el JSONL de trafico del gateway (gateway/logs/traffic.jsonl) para entender
como los clientes (Claude Code, qwen-code, opencode) piden los modelos y como el
clasificador 'auto' los rutea. Sirve para ir ajustando el ruteo.

Uso:
  # local (si copiaste el jsonl):
  python3 scripts/analyze-traffic.py /ruta/traffic.jsonl
  # remoto (lee de airouter por ssh):
  ssh root@airouter.core.sied.ar 'cat /opt/llm-gateway-router/gateway/logs/traffic.jsonl' | python3 scripts/analyze-traffic.py -
"""
import json
import sys
from collections import Counter, defaultdict

TARGETS = {"llama3.1:8b", "agile-coder-ops", "system-architect", "qwen3-coder:30b", "qwen3.6:35b"}


def load(path):
    f = sys.stdin if path == "-" else open(path, encoding="utf-8")
    rows = []
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def first_user(messages):
    for m in messages or []:
        if m.get("role") == "user":
            return (m.get("content") or "").replace("\n", " ")[:90]
    return ""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "-"
    rows = load(path)
    if not rows:
        print("Sin registros.")
        return

    by_model = Counter(r.get("requested_model") for r in rows)
    by_status = Counter(r.get("status") for r in rows)
    latencies = defaultdict(list)
    for r in rows:
        if r.get("latency_ms") is not None:
            latencies[r.get("requested_model")].append(r["latency_ms"])

    print(f"== Trafico: {len(rows)} requests ==\n")
    print("Por modelo solicitado (lo que pide el cliente):")
    for model, n in by_model.most_common():
        lat = latencies.get(model, [])
        avg = f", lat media {round(sum(lat)/len(lat))}ms" if lat else ""
        print(f"  {model or '?':24} {n:4}{avg}")

    print(f"\nPor status: {dict(by_status)}")

    # Lo que el clasificador termino eligiendo (registros cuyo modelo es un destino real).
    targets = Counter(r.get("requested_model") for r in rows if r.get("requested_model") in TARGETS)
    if targets:
        print("\nDestinos finales (a donde fue a parar el trabajo):")
        for t, n in targets.most_common():
            print(f"  {t:24} {n:4}")

    # Muestras de prompts por modelo, para evaluar si la clasificacion fue acertada.
    print("\nEjemplos de prompts por modelo (revisar si el ruteo tiene sentido):")
    seen = defaultdict(int)
    for r in rows:
        m = r.get("requested_model")
        if seen[m] < 3 and r.get("messages"):
            seen[m] += 1
            print(f"  [{m}] {first_user(r['messages'])}")


if __name__ == "__main__":
    main()
