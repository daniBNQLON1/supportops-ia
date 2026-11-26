# Observabilidad para un agente de IA (ISY1010 · EP3)

Kit de observabilidad y trazabilidad: instrumentación (spans + logs JSONL), métricas (precisión, consistencia, errores, latencia p50/p95/p99,
CPU, memoria, tokens), análisis de trazas con hallazgos automáticos, dashboard, pruebas, informe y guía de defensa.

> ⚠ **Los datos incluidos provienen de un agente DEMO sintético** (`demo/`). Antes de entregar, conecte su agente real:
> [`docs/ADAPTAR_A_SU_AGENTE.md`](docs/ADAPTAR_A_SU_AGENTE.md), regenere todo y complete las secciones marcadas con `[COMPLETAR]` del informe.

## Ejecución rápida (Python ≥ 3.10; solo requiere pandas, numpy, psutil, matplotlib, python-docx, pytest)
```bash
pip install -r requirements.txt
./run_all.sh            # logs -> análisis -> dashboard -> pruebas -> informe
open dashboard/index.html   # (o abrirlo con el navegador)
```
Paso a paso:
```bash
python -m scripts.run_experiments --mode baseline  --out data/logs/baseline.jsonl
python -m scripts.run_experiments --mode optimized --out data/logs/optimized.jsonl
python -m scripts.analyze --logs data/logs/baseline.jsonl data/logs/optimized.jsonl   # reports/analysis.json
python -m scripts.build_dashboard                                                     # dashboard/index.html
python -m pytest -q tests                                                             # pruebas
python -m scripts.make_report                                                         # reports/Informe_EP3.docx
streamlit run dashboard/streamlit_app.py                                              # opcional
```
## Agente principal: SupportOps (el de la EP2, LangGraph + Groq)
`agent/supportops.py` es el agente de soporte técnico de la EP2 (`create_react_agent`, herramientas `registrar_ticket` y
`consultar_politicas_internas`, memoria `MemorySaver`) con observabilidad: un callback de LangChain (`TraceHandler`) convierte cada llamada al LLM y a
herramientas en spans. `BASELINE` = el código de la EP2 tal cual; `OPTIMIZED` = mejoras justificadas por los logs (guardrail contra inyección,
enmascarado de PII, reintentos/timeout, límite de concurrencia, escritura atómica de tickets con lock e IDs únicos).
```powershell
pip install langgraph langchain-groq
$env:GROQ_API_KEY="su_clave_de_groq"          # NUNCA la escriba en el cuaderno ni en GitHub
python -m scripts.run_supportops --mode baseline  --out data/real/baseline.jsonl  --quick
python -m scripts.run_supportops --mode optimized --out data/real/optimized.jsonl --quick
python -m scripts.analyze --logs data/real/baseline.jsonl data/real/optimized.jsonl --slo slo_real.json --real
python -m scripts.build_dashboard
python -m scripts.make_report
```
Cada corrida escribe también `data/real/audit_<modo>.json` (tickets que el agente dijo crear vs. tickets guardados, IDs duplicados).
Escenarios: `complete`, `incomplete_then_complete` (prueba la memoria), `policy`, `noisy`, `long_input`, `injection`, `pii`, `burst` (concurrencia).
Correcto = usó la herramienta esperada (`TOOL:...`), no la usó cuando faltaban datos (`NOTOOL`), fue bloqueado (`BLOCKED`) o contiene la frase clave.

## Agente alternativo de FAQ (Gemini / compatible OpenAI)
`agent/faq_agent.py` es un agente de atención a usuarios: guardrail → recuperación sobre `agent/knowledge_base.json` → LLM Gemini → herramienta → postproceso.
Tiene dos configuraciones (`BASELINE` ingenua y `OPTIMIZED`) para medir el antes/después con datos reales.
1. Clave gratis en https://aistudio.google.com/apikey (no la suba a GitHub; `.env` está en `.gitignore`).
2. **Edite `agent/knowledge_base.json`** con SU institución/tema (preguntas, respuesta, frase clave, consultas ambiguas).
3. PowerShell:
```powershell
$env:GEMINI_API_KEY="su_clave"
python -m scripts.check_gemini                       # prueba la clave y el modelo
python -m scripts.run_real --mode baseline  --out data/real/baseline.jsonl  --quick
python -m scripts.run_real --mode optimized --out data/real/optimized.jsonl --quick
python -m scripts.analyze --logs data/real/baseline.jsonl data/real/optimized.jsonl --slo slo_real.json --real
python -m scripts.build_dashboard
python -m scripts.make_report
```
**Otro proveedor (Ollama local, Groq, OpenRouter, OpenAI…)** sin tocar código:
```powershell
$env:LLM_PROVIDER="openai_compat"
$env:LLM_BASE_URL="http://localhost:11434/v1"   # Ollama; para otros use la URL base de su servicio
$env:LLM_MODEL="llama3.2:3b"                    # nombre del modelo en ese servicio
$env:LLM_API_KEY="..."                           # no hace falta en Ollama
```
Con Ollama: instalar desde ollama.com y ejecutar `ollama pull llama3.2:3b` una vez.

La capa gratuita limita ~15 peticiones/min; `--throttle 4.5` lo respeta (una corrida `--quick` ≈ 8 min). El escenario `burst` envía peticiones
concurrentes y puede producir errores 429 reales: es un hallazgo legítimo para analizar. Ajuste `slo_real.json` (la latencia de un LLM real es de segundos).
La herramienta `consulta_estado_tramite` es simulada: reemplácela por su sistema real si lo tienen.

## Estructura
| Ruta | Contenido |
|---|---|
| `observability/` | `tracer.py` (trazas), `metrics.py` (métricas y SLO), `analysis.py` (cuellos de botella, anomalías, hallazgos), `safety.py` (PII, inyección, hash) |
| `demo/` | agente sintético (modo baseline/optimized) y golden set con 7 escenarios |
| `scripts/` | experimentos, análisis, dashboard, informe |
| `dashboard/` | `index.html` (autocontenido, interactivo), `streamlit_app.py` (alternativo) |
| `tests/` | pruebas unitarias · evidencia: `reports/pytest_results.xml` |
| `docs/` | adaptación a su agente, seguridad/ética, guía de defensa, capturas, bocetos (`BOCETO_ARQUITECTURA.md`) |

Esquema de cada línea de log: `trace_id, ts, run, scenario, input_hash, input_len, status(ok|error|blocked), error_type, error_step, latency_ms, cpu_ms, rss_mb, tokens_in/out, expected, correct, output_hash, output_masked, spans[{name, ms, status, error, retries}]`.

Reproducibilidad: semilla `--seed 42`; la ráfaga usa hilos, por lo que las cifras de latencia/errores varían levemente entre ejecuciones.
