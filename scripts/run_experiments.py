"""Ejecuta el golden set contra el agente y genera logs JSONL.

    python -m scripts.run_experiments --mode baseline  --out data/logs/baseline.jsonl
    python -m scripts.run_experiments --mode optimized --out data/logs/optimized.jsonl

Cada modo se ejecuta en un proceso aparte para que la medición de memoria (RSS) no se contamine.
"""
from __future__ import annotations

import argparse
import random
from concurrent.futures import ThreadPoolExecutor

from demo.agent import DemoAgent
from demo.dataset import build
from observability.tracer import Tracer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "optimized"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=8, help="hilos concurrentes del escenario 'burst'")
    a = ap.parse_args()

    tracer = Tracer(a.out, run_label=a.mode)
    tracer.reset()
    agent = DemoAgent(optimized=a.mode == "optimized")
    items = build(a.seed)

    def one(it):
        sc, i, rep, text, expected = it
        rng = random.Random(f"{a.seed}|{sc}|{i}|{rep}|{a.mode}")
        try:
            with tracer.trace(scenario=sc, input_text=text, expected=expected) as t:
                agent.run(t, text, rng)
        except Exception:
            pass  # ya quedó registrado en el log por el tracer

    seq = [it for it in items if it[0] != "burst"]
    burst = [it for it in items if it[0] == "burst"]
    for it in seq:
        one(it)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, burst))
    print(f"[{a.mode}] {len(items)} ejecuciones -> {a.out}")


if __name__ == "__main__":
    main()
