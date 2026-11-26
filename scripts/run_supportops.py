"""Ejecuta el golden set contra SupportOps (LangGraph + Groq) y genera logs JSONL + auditoría de tickets.

PowerShell:
    pip install langgraph langchain-groq
    $env:GROQ_API_KEY="su_clave"
    python -m scripts.run_supportops --mode baseline  --out data/real/baseline.jsonl  --quick
    python -m scripts.run_supportops --mode optimized --out data/real/optimized.jsonl --quick
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent.supportops import BASELINE, OPTIMIZED, PLACEHOLDERS, PRIORIDADES, SupportOpsAgent
from agent.supportops_dataset import build
from observability.safety import count_pii
from observability.tracer import Tracer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "optimized"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=4, help="hilos del escenario 'burst'")
    ap.add_argument("--throttle", type=float, default=3.0, help="segundos entre conversaciones secuenciales")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("GROQ_API_KEY"):
        sys.exit('Falta GROQ_API_KEY. En PowerShell:  $env:GROQ_API_KEY="su_clave"')

    out = Path(a.out)
    tickets = out.with_name(f"tickets_{a.mode}.json")
    tickets.unlink(missing_ok=True)
    tracer = Tracer(out, run_label=a.mode)
    tracer.reset()
    agent = SupportOpsAgent(BASELINE if a.mode == "baseline" else OPTIMIZED, tickets)
    convs = build(a.seed, a.quick)
    seq = [c for c in convs if c[0] != "burst"]
    burst = [c for c in convs if c[0] == "burst"]
    done = [0]

    def run_conv(c, pause=0.0):
        sc, rep, turns = c
        thread_id = f"{a.mode}-{sc}-{rep}-{uuid.uuid4().hex[:6]}"      # memoria independiente por conversación
        for text, expected in turns:
            try:
                with tracer.trace(scenario=sc, input_text=text, expected=expected) as t:
                    agent.run(t, text, thread_id)
            except Exception:
                pass                                                  # ya quedó registrado
            done[0] += 1
            if done[0] % 10 == 0:
                print(f"  {done[0]} turnos", flush=True)
            if pause and sc != "injection":
                time.sleep(pause)

    for c in seq:
        run_conv(c, a.throttle)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(run_conv, burst))

    # Auditoría de integridad: tickets que el agente dijo crear vs. tickets realmente guardados
    ok_calls = 0
    for line in out.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        ok_calls += sum(1 for s in r["spans"] if s["name"] == "tool" and s.get("tool") == "registrar_ticket" and s["status"] == "ok")
    saved = json.loads(tickets.read_text(encoding="utf-8")) if tickets.exists() else []
    audit = {"llamadas_exitosas_registrar_ticket": ok_calls, "tickets_en_archivo": len(saved),
             "ids_unicos": len({t["ticket_id"] for t in saved}),
             "tickets_perdidos": ok_calls - len(saved), "ids_duplicados": len(saved) - len({t["ticket_id"] for t in saved}),
             "pii_en_tickets": sum(1 for t in saved if sum(count_pii(str(t.get(k, ""))) for k in ("usuario", "departamento", "descripcion"))),  # tickets con PII (no cuenta el ID)
             "tickets_datos_invalidos": sum(1 for t in saved if any(str(t.get(k, "")).strip().lower() in PLACEHOLDERS for k in ("usuario", "departamento", "descripcion"))),
             "prioridad_no_estandar": sum(1 for t in saved if t.get("prioridad") not in PRIORIDADES)}
    out.with_name(f"audit_{a.mode}.json").write_text(json.dumps(audit, indent=1), encoding="utf-8")
    print(f"[{a.mode}] {done[0]} turnos -> {a.out}\nAuditoría de tickets: {audit}")


if __name__ == "__main__":
    main()
