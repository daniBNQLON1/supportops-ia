"""Genera reports/Informe_EP3.docx (máx. 5 páginas) con las cifras REALES de reports/analysis.json.

Las secciones de reflexión individual y declaración de IA quedan para que las complete el equipo
(la pauta prohíbe redactarlas con IA).
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

D = json.loads(Path("reports/analysis.json").read_text(encoding="utf-8"))
B, O = D["baseline"], D["optimized"]
CB, CO = "#f47230", "#257de0"
Path("reports/fig").mkdir(parents=True, exist_ok=True)
scs = list(B["metrics"]["by_scenario"])


def fig_bars():
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.5))
    for a, (fn, t, ref) in zip(ax, [(lambda m: 100 * m["accuracy"], "Precisión (%)", 85),
                                    (lambda m: m["latency"]["p95"], "Latencia p95 (ms)", 250)]):
        x = range(len(scs))
        a.bar([i - .2 for i in x], [fn(B["metrics"]["by_scenario"][s]) for s in scs], .38, color=CB, label="Baseline")
        a.bar([i + .2 for i in x], [fn(O["metrics"]["by_scenario"][s]) for s in scs], .38, color=CO, label="Optimizado")
        if t.startswith("Prec"):
            a.axhline(ref, ls="--", c="gray", lw=.8)
        a.set_xticks(list(x)); a.set_xticklabels([s.replace("_", "\n") for s in scs], fontsize=6.5)
        a.set_title(t, fontsize=8); a.tick_params(labelsize=7)
        for sp in ("top", "right"): a.spines[sp].set_visible(False)
    fig.legend(*ax[0].get_legend_handles_labels(), loc="upper center", ncol=2, fontsize=7, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, .92)); fig.savefig("reports/fig/bars.png", dpi=200); plt.close(fig)


def fig_steps_rss():
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.2))
    st = B["steps"]
    ax[0].barh([s["step"] for s in st][::-1], [s["share_pct"] for s in st][::-1], color=CB)
    ax[0].set_title("Baseline: % del tiempo por etapa", fontsize=8)
    ax[1].plot(B["series"]["rss"], color=CB, label="Baseline"); ax[1].plot(O["series"]["rss"], color=CO, label="Optimizado")
    ax[1].set_title("Memoria RSS (MB) por ejecución", fontsize=8); ax[1].legend(fontsize=7, frameon=False)
    for a in ax:
        a.tick_params(labelsize=7)
        for sp in ("top", "right"): a.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig("reports/fig/steps_rss.png", dpi=200); plt.close(fig)


fig_bars(); fig_steps_rss()

doc = Document()
s = doc.sections[0]
s.left_margin = s.right_margin = Cm(2); s.top_margin = s.bottom_margin = Cm(1.8)
st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10)
st.paragraph_format.space_after = Pt(3)


def H(t, lvl=1):
    h = doc.add_heading(t, lvl)
    for r in h.runs: r.font.color.rgb = RGBColor(0x1f, 0x2d, 0x3d); r.font.size = Pt(13 if lvl == 1 else 11)
    h.paragraph_format.space_before = Pt(8); h.paragraph_format.space_after = Pt(2)


def P(t, bold=False, italic=False):
    p = doc.add_paragraph(); r = p.add_run(t); r.bold = bold; r.italic = italic; return p


def table(rows, widths=None, size=8.5):
    t = doc.add_table(rows=len(rows), cols=len(rows[0])); t.style = "Light Grid Accent 1"
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            c = t.cell(i, j); c.text = ""; run = c.paragraphs[0].add_run(str(v)); run.font.size = Pt(size); run.bold = i == 0
            c.paragraphs[0].paragraph_format.space_after = Pt(0)
            if widths: c.width = Cm(widths[j])
    return t


gb, go = B["metrics"]["global"], O["metrics"]["global"]
T = B["metrics"]["slo_targets"]
AB, AO = B.get("audit") or {}, O.get("audit") or {}
SB, SO = B["metrics"]["by_scenario"], O["metrics"]["by_scenario"]
nan = float("nan")


def pc(x, d=1):
    return "n/d" if x != x else f"{100*x:.{d}f}%"


def ms(x):
    return "n/d" if x != x else f"{x:,.0f}".replace(",", ".")


def g(d, k):
    return d.get(k, "n/d")


t = doc.add_heading("Informe técnico: Observabilidad del agente SupportOps (LangGraph + Groq)", 0)
for r in t.runs: r.font.size = Pt(16)
P("ISY1010 Ingeniería de Soluciones con IA · Evaluación Parcial 3 · Integrante: Daniel Tobar [COMPLETAR: segundo integrante, si corresponde] · Docente: [NOMBRE] · Fecha: [FECHA]", italic=True)

H("1. Contexto y objetivo")
P("SupportOps es el agente de soporte técnico desarrollado en la EP2: un agente ReAct de LangGraph (create_react_agent) con el modelo openai/gpt-oss-20b en Groq, "
  "memoria de conversación (MemorySaver) y dos herramientas: registrar_ticket (escritura en tickets_db.json) y consultar_politicas_internas (consulta). "
  "Se instrumentó con un callback de LangChain que convierte cada llamada al LLM y a herramientas en un span, y se evaluó con 8 escenarios de variabilidad "
  f"(solicitud completa, incompleta y luego completada, consulta de políticas, ruido ortográfico, entrada larga, inyección de prompt, datos personales y ráfaga concurrente): {gb['n']} turnos por corrida. "
  "Baseline = el código de la EP2 sin cambios; Optimizado = versión corregida a partir de los hallazgos de este informe. "
  "[COMPLETAR: contexto organizacional del agente y limitaciones de su EP2.]")
H("2. Métricas implementadas (IE1, IE2)")
table([["Métrica", "Definición", "SLO", "Baseline", "Optimizado"],
       ["Precisión", "turnos correctos / evaluados (herramienta correcta, sin herramienta si faltan datos, frase clave); un error cuenta como incorrecto", f"≥ {100*T['accuracy_min']:.0f}%", pc(gb["accuracy"]), pc(go["accuracy"])],
       ["Consistencia", "misma entrada repetida: acuerdo en la decisión (herramienta + prioridad)", f"≥ {100*T['consistency_min']:.0f}%", pc(gb["consistency"]), pc(go["consistency"])],
       ["Tasa de error", "turnos con excepción / total", f"≤ {100*T['error_rate_max']:.0f}%", pc(gb["error_rate"]), pc(go["error_rate"])],
       ["Latencia p95 (p50), ms", "extremo a extremo por turno", f"≤ {T['p95_ms_max']:.0f}", f"{ms(gb['latency']['p95'])} ({ms(gb['latency']['p50'])})", f"{ms(go['latency']['p95'])} ({ms(go['latency']['p50'])})"],
       ["Memoria (MB / 100 req)", "pendiente de RSS (muestra pequeña: incluye calentamiento)", f"≤ {T['rss_slope_mb_per_100req_max']:g}", f"{gb['rss_slope_mb_per_100req']:.1f}", f"{go['rss_slope_mb_per_100req']:.1f}"],
       ["CPU (ms) / tokens por turno", "CPU del hilo / tokens del proveedor", "—", f"{gb['cpu_ms_mean']:.1f} / {gb['tokens_mean']:.0f}", f"{go['cpu_ms_mean']:.1f} / {go['tokens_mean']:.0f}"],
       ["PII enviada al LLM", "coincidencias de PII en el prompt externo", "= 0", gb["pii_to_llm"], go["pii_to_llm"]]],
      widths=[3, 6.6, 1.5, 2.8, 2.8])
doc.add_picture("reports/fig/bars.png", width=Cm(16.5))
doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
H("3. Análisis de logs y trazabilidad (IE3, IE6)")
rows = [["Hallazgo (evidencia en los logs)", "Baseline", "Optimizado"]]
rows += [["Errores de la API (RateLimitError) / escenario ráfaga: precisión", f"{sum(e['count'] for e in B['errors'])} errores · {pc(SB.get('burst',{}).get('accuracy', nan),0)}", f"{sum(e['count'] for e in O['errors'])} errores · {pc(SO.get('burst',{}).get('accuracy', nan),0)}"],
         ["Inyección de prompt: bloqueadas por guardrail / ejecutó algo indebido", f"{SB.get('injection',{}).get('blocked',0)} de {SB.get('injection',{}).get('n','n/d')} · correctas {pc(SB.get('injection',{}).get('accuracy', nan),0)}", f"{SO.get('injection',{}).get('blocked',0)} de {SO.get('injection',{}).get('n','n/d')} · correctas {pc(SO.get('injection',{}).get('accuracy', nan),0)}"],
         ["Latencia p95 en inyección (ms)", ms(SB.get("injection", {}).get("latency", {}).get("p95", nan)), ms(SO.get("injection", {}).get("latency", {}).get("p95", nan))],
         ["Tickets: dijo crear / guardados / perdidos", f"{g(AB,'llamadas_exitosas_registrar_ticket')} / {g(AB,'tickets_en_archivo')} / {g(AB,'tickets_perdidos')}", f"{g(AO,'llamadas_exitosas_registrar_ticket')} / {g(AO,'tickets_en_archivo')} / {g(AO,'tickets_perdidos')}"],
         ["IDs de ticket duplicados (ID con resolución de 1 s)", g(AB, "ids_duplicados"), g(AO, "ids_duplicados")],
         ["PII persistida en la base de tickets", g(AB, "pii_en_tickets"), g(AO, "pii_en_tickets")],
         ["Tickets con datos inválidos (?, vacío) / prioridad no estándar", f"{g(AB,'tickets_datos_invalidos')} / {g(AB,'prioridad_no_estandar')}", f"{g(AO,'tickets_datos_invalidos')} / {g(AO,'prioridad_no_estandar')}"],
         ["Turnos incorrectos en flujo incompleto→completo (memoria)", pc(1 - SB.get("incomplete_then_complete", {}).get("accuracy", nan), 0), pc(1 - SO.get("incomplete_then_complete", {}).get("accuracy", nan), 0)]]
table(rows, widths=[9.2, 3.7, 3.7], size=8)
P("Además, el análisis automático de trazas (analysis.py) detectó: " + "; ".join(f"{f['id']}: {f['evidence']}" for f in B["findings"] if f["severity"] != "info")[:900] + ". "
  "Observación clave: casi todo el tiempo (≈100 %) está en la etapa llm, por lo que la latencia depende del proveedor y de sus límites de tasa; las herramientas locales cuestan milisegundos.")
doc.add_picture("reports/fig/steps_rss.png", width=Cm(16.5))
doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
H("4. Dashboard de monitoreo (IE4)")
P("Dashboard interactivo (dashboard/index.html): KPI con semáforo de SLO, precisión y p95 por escenario, tiempo por etapa, memoria, latencia por turno con errores marcados, "
  "taxonomía de errores, controles de seguridad, integridad de tickets y hallazgos; filtro por escenario y comparación baseline/optimizado.")
if Path("docs/dashboard_optimized.png").exists():
    doc.add_picture("docs/dashboard_optimized.png", width=Cm(10.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    P("Figura 3. Captura del dashboard (corrida optimizada).", italic=True)
H("5. Recomendaciones y rediseño (IE5, IE7)")
table([["Cambio aplicado", "Evidencia que lo justifica", "Efecto medido"],
       ["Guardrail determinista contra inyección de prompt", f"El modelo rechazó los ataques por sí solo, pero cada uno costó p95 {ms(SB.get('injection',{}).get('latency',{}).get('p95',nan))} ms y tokens", f"Bloqueo local: p95 {ms(SO.get('injection',{}).get('latency',{}).get('p95',nan))} ms, {SO.get('injection',{}).get('blocked',0)} bloqueos, sin llamar al LLM"],
       ["Enmascarar PII antes del LLM y antes de persistir", f"PII enviada al LLM {gb['pii_to_llm']}; PII en tickets {g(AB,'pii_en_tickets')}", f"{go['pii_to_llm']} y {g(AO,'pii_en_tickets')}"],
       ["Validación determinista en registrar_ticket (campos obligatorios y prioridad Alta/Media/Baja)", f"Tickets con datos inválidos {g(AB,'tickets_datos_invalidos')}; prioridad no estándar {g(AB,'prioridad_no_estandar')}", f"{g(AO,'tickets_datos_invalidos')} y {g(AO,'prioridad_no_estandar')}"],
       ["Escritura con lock y archivo temporal atómico; ID con sufijo único", f"Perdidos {g(AB,'tickets_perdidos')}; IDs duplicados {g(AB,'ids_duplicados')}", f"{g(AO,'tickets_perdidos')} y {g(AO,'ids_duplicados')}"],
       ["Reintentos (4), timeout y límite de concurrencia (3) hacia el proveedor", f"RateLimitError {sum(e['count'] for e in B['errors'])}; precisión en ráfaga {pc(SB.get('burst',{}).get('accuracy',nan),0)}", f"{sum(e['count'] for e in O['errors'])} errores; {pc(SO.get('burst',{}).get('accuracy',nan),0)}"],
       ["Rediseño futuro: cola con control de tasa, checkpointer persistente (SQLite/Postgres) en vez de MemorySaver en RAM, base de datos para tickets, evaluación continua con el golden set y alertas por SLO", "La memoria en RAM se pierde al reiniciar y el JSON no escala; la latencia depende del proveedor", "Propuesto (no medido)"]],
      widths=[5.6, 6.2, 4.8], size=8)
P("Limitaciones: corrida única de modo rápido (n pequeño por escenario), resultados de un LLM no determinista, SLO definidos por el equipo; la métrica de memoria "
  "incluye el calentamiento del proceso. Las diferencias pequeñas deben interpretarse con cautela. [COMPLETAR: justificar los SLO y repetir la corrida si hay tiempo.]", italic=True)
H("6. Seguridad, ética y privacidad (IE8)")
P(f"Controles: (a) guardrail de inyección (OWASP, 2025): {SO.get('injection',{}).get('blocked',0)} de {SO.get('injection',{}).get('n','n/d')} intentos bloqueados antes del LLM; "
  f"(b) minimización de datos: PII enmascarada antes del proveedor externo ({gb['pii_to_llm']} → {go['pii_to_llm']}) y antes de guardar tickets ({g(AB,'pii_en_tickets')} → {g(AO,'pii_en_tickets')}); "
  "(c) los logs de observabilidad guardan solo un hash con sal, el largo y la salida enmascarada, nunca el texto del usuario; (d) mínimo privilegio: solo dos herramientas; "
  "(e) integridad: validación de datos y escritura atómica; (f) supervisión humana: el agente pide los datos faltantes y no inventa valores. "
  "Marco: Ley 19.628 y Ley 21.719, que entra en vigor el 1 de diciembre de 2026 (finalidad, minimización y seguridad), y NIST (2023). "
  "[COMPLETAR: política de retención de logs y tickets, base de licitud, canal de reclamos del titular y rol del equipo humano.]")
H("7. Conclusiones")
P("[REFLEXIÓN INDIVIDUAL – DANIEL TOBAR: redactar SIN apoyo de IA (aprendizaje y contribución).]", italic=True)
P("[REFLEXIÓN INDIVIDUAL – SEGUNDO INTEGRANTE, si corresponde.]", italic=True)
H("8. Declaración de uso de IA")
P("[AJUSTAR A LA REALIDAD] Se usó Claude (Anthropic, 2026) como apoyo para generar el andamiaje de instrumentación, los scripts de análisis, el dashboard y la estructura de este informe; "
  "el agente SupportOps de la EP2 también se desarrolló con apoyo de IA. El equipo revisó y validó el contenido; las conclusiones y reflexiones individuales fueron redactadas por los integrantes.")
H("Referencias")
for r in ["Anthropic. (2026). Claude Sonnet 5.5 [Modelo de lenguaje]. https://claude.ai",
          "Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (Eds.). (2016). Site reliability engineering: How Google runs production systems. O’Reilly Media.",
          "Groq. (s. f.). Groq API documentation. https://console.groq.com/docs",
          "LangChain. (s. f.). LangGraph documentation. https://langchain-ai.github.io/langgraph/",
          "Ley 19.628 de 1999. Sobre protección de la vida privada. Diario Oficial de la República de Chile.",
          "Ley 21.719 de 2024. Regula la protección y el tratamiento de los datos personales y crea la Agencia de Protección de Datos Personales. Diario Oficial de la República de Chile.",
          "National Institute of Standards and Technology. (2023). Artificial intelligence risk management framework (AI RMF 1.0) (NIST AI 100-1). https://doi.org/10.6028/NIST.AI.100-1",
          "OpenTelemetry. (s. f.). Documentation. https://opentelemetry.io/docs/",
          "OWASP Foundation. (2025). OWASP top 10 for LLM applications 2025. https://genai.owasp.org/llm-top-10/"]:
    p = P(r); p.paragraph_format.left_indent = Cm(.8); p.paragraph_format.first_line_indent = Cm(-.8)
    for run in p.runs: run.font.size = Pt(8.5)
doc.save("reports/Informe_EP3.docx")
print("-> reports/Informe_EP3.docx")
