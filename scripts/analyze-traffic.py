#!/usr/bin/env python3
"""
Analiza el JSONL de trafico del gateway (gateway/logs/traffic.jsonl) para entender
como los clientes (Claude Code, qwen-code, opencode) piden los modelos y como el
clasificador 'auto' los rutea. Sirve para ir ajustando el ruteo.

Uso:
  # resumen (default):
  ssh root@airouter.core.sied.ar 'cat /opt/llm-gateway-router/gateway/logs/traffic.jsonl' | python3 scripts/analyze-traffic.py -
  # volcar los requests COMPLETOS de un modelo (para disenar el interceptor on-prem):
  ssh ... 'cat .../traffic.jsonl' | python3 scripts/analyze-traffic.py - --dump claude-sonnet-4-6
"""
import json
import sys
from collections import Counter, defaultdict

TARGETS = {"llama3.1:8b", "agile-coder-ops", "system-architect", "qwen3-coder:30b", "qwen3.6:35b"}
SKIP_PREFIXES = ("<system-reminder>", "<local-command-caveat>", "<command-")


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


def real_user_prompt(messages):
    """Ultimo mensaje user que no sea system-reminder/caveat (el pedido real)."""
    best = ""
    for m in messages or []:
        if m.get("role") != "user":
            continue
        c = m.get("content") or ""
        if not isinstance(c, str):
            continue
        stripped = c.lstrip()
        if stripped.startswith(SKIP_PREFIXES):
            continue
        best = c  # nos quedamos con el ultimo que aplique
    return best.replace("\n", " ")[:110]


def dump_model(rows, model):
    """Vuelca los requests completos de un modelo (JSON por request)."""
    n = 0
    for r in rows:
        if r.get("requested_model") != model:
            continue
        n += 1
        print(json.dumps({
            "ts": r.get("ts"),
            "status": r.get("status"),
            "messages": r.get("messages"),
            "response_text": r.get("response_text"),
            "tool_calls": r.get("tool_calls"),
            "usage": r.get("usage"),
        }, ensure_ascii=False, indent=2))
        print("=" * 80)
    print(f"\n# {n} requests de {model}", file=sys.stderr)


def main():
    args = [a for a in sys.argv[1:]]
    path = args[0] if args else "-"
    rows = load(path)
    if not rows:
        print("Sin registros.")
        return

    if "--dump" in args:
        model = args[args.index("--dump") + 1]
        dump_model(rows, model)
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
    print("\nEjemplos de pedido REAL por modelo (ultimo user, sin system-reminder):")
    seen = defaultdict(int)
    for r in rows:
        m = r.get("requested_model")
        if seen[m] < 3 and r.get("messages"):
            prompt = real_user_prompt(r["messages"])
            if prompt:
                seen[m] += 1
                print(f"  [{m}] {prompt}")
    print("\n(para ver requests completos de un modelo: --dump <modelo>)")


if __name__ == "__main__":
    main()
