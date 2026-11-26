"""Ejecuta el golden set contra el agente REAL (Gemini) y genera logs JSONL.

PowerShell:   $env:GEMINI_API_KEY="su_clave"
    python -m scripts.run_real --mode baseline  --out data/real/baseline.jsonl  --quick
    python -m scripts.run_real --mode optimized --out data/real/optimized.jsonl --quick

--throttle  segundos de espera entre peticiones secuenciales (capa gratuita ≈ 15 req/min -> 4.5 s)
--quick     menos repeticiones (≈ 90 peticiones por corrida, ~8 min con throttle 4.5)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from agent.dataset import build
from agent.faq_agent import BASELINE, OPTIMIZED, FAQAgent
from observability.tracer import Tracer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "optimized"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=6, help="hilos del escenario 'burst'")
    ap.add_argument("--throttle", type=float, default=4.5)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    prov = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if prov == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Falta GEMINI_API_KEY (o use LLM_PROVIDER=openai_compat; ver README).")

    tracer = Tracer(a.out, run_label=a.mode)
    tracer.reset()
    agent = FAQAgent(BASELINE if a.mode == "baseline" else OPTIMIZED)
    items = build(a.seed, a.quick)
    seq = [it for it in items if it[0] != "burst"]
    burst = [it for it in items if it[0] == "burst"]
    total = len(items)
    done = [0]

    def one(it, pause=0.0):
        sc, i, rep, text, expected = it
        try:
            with tracer.trace(scenario=sc, input_text=text, expected=expected) as t:
                agent.run(t, text)
        except Exception:
            pass  # el tracer ya registró el error
        done[0] += 1
        if done[0] % 10 == 0:
            print(f"  {done[0]}/{total}", flush=True)
        if pause and sc != "injection":
            time.sleep(pause)

    for it in seq:
        one(it, a.throttle)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, burst))
    print(f"[{a.mode}] {total} ejecuciones -> {a.out}")


if __name__ == "__main__":
    main()
