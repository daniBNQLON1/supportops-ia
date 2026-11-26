# Cómo conectar SU agente real (obligatorio para la entrega)

El agente de `demo/` es **sintético**. Para la evaluación, las cifras deben venir de su agente de la EP1.

1. Copie `observability/` a su proyecto (o instale con `pip install -e .` si agrega un pyproject).
2. Envuelva cada petición y cada etapa:

```python
from observability.tracer import Tracer, span
tracer = Tracer("data/logs/real.jsonl", run_label="real")

def atender(pregunta, esperado=None):
    with tracer.trace(scenario="normal", input_text=pregunta, expected=esperado) as t:
        with span("guardrail"): ...
        with span("retrieve"):  docs = buscar(pregunta)
        with span("llm"):
            resp, tin, tout = llamar_llm(pregunta, docs)   # tokens que reporta su proveedor
            t.add_tokens(tin, tout)
        with span("tool", tool="nombre_herramienta"): ...
        t.set_output(resp)
        return resp
```
3. Cree su golden set (preguntas + frase clave esperada) incluyendo escenarios con variabilidad: ruido, entradas largas,
   ambigüedad, datos personales, intentos de inyección y carga concurrente. Repita cada input ≥3 veces (consistencia).
4. Ejecute una corrida "baseline" (su agente tal cual) y otra "optimized" (tras sus correcciones) → dos `.jsonl`.
5. `python -m scripts.analyze --logs data/logs/baseline.jsonl data/logs/optimized.jsonl` y luego `scripts.build_dashboard` y `scripts.make_report`.
6. Ajuste los SLO en `observability/metrics.py` y **justifíquelos** en el informe.
7. Use `t.attrs["pii_to_llm"] = count_pii(prompt)` si quiere medir PII enviada al proveedor.

Si su agente corre en n8n/LangChain/etc.: el tracer es solo un wrapper; lo importante es el esquema de log (ver `tracer.py`).
