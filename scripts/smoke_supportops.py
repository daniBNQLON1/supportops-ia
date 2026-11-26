"""Prueba corta (1-2 llamadas) de SupportOps con observabilidad. Muestra errores completos.
    $env:GROQ_API_KEY="su_clave"
    py -3.12 -m scripts.smoke_supportops
"""
import json
import os
import sys
import traceback

from agent.supportops import OPTIMIZED, SupportOpsAgent
from observability.tracer import Tracer

if not os.environ.get("GROQ_API_KEY"):
    sys.exit('Falta GROQ_API_KEY.  $env:GROQ_API_KEY="su_clave"')
out = "data/real/smoke.jsonl"
tr = Tracer(out, "smoke"); tr.reset()
agent = SupportOpsAgent(OPTIMIZED, "data/real/tickets_smoke.json")
for text, exp in [("Hola, se me rompió la pantalla del notebook.", "NOTOOL"),
                  ("Soy Juan Pérez de Marketing. Ponle prioridad Media.", "TOOL:registrar_ticket")]:
    try:
        with tr.trace("smoke", text, expected=exp) as t:
            r = agent.run(t, text, "smoke-1")
        print(f"\nUsuario: {text}\nAgente : {r}")
    except Exception:
        traceback.print_exc()
rec = [json.loads(l) for l in open(out, encoding="utf-8")]
for r in rec:
    print(f"\nstatus={r['status']} correct={r['correct']} latencia={r['latency_ms']:.0f}ms tokens={r['tokens_in']}+{r['tokens_out']} "
          f"tools={r['tools_called']} spans={[(s['name'], s['ms']) for s in r['spans']]}")
print("\nSi ambos 'correct=True' y ves spans llm/tool, la instrumentación funciona.")
