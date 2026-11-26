"""SupportOps (agente de la EP2: LangGraph + Groq) instrumentado con observabilidad.

El agente es el mismo de la EP2 (create_react_agent, 2 herramientas, MemorySaver). Se agrega:
  · TraceHandler: callback de LangChain que convierte cada llamada al LLM y a herramientas en un span.
  · BASELINE  = código de la EP2 tal cual (sin guardrail, sin enmascarar PII, escritura de tickets sin bloqueo).
  · OPTIMIZED = mejoras justificadas por los logs (guardrail, minimización de PII, reintentos/timeout,
                límite de concurrencia, escritura atómica con lock e IDs únicos).

Requiere:  pip install langgraph langchain-groq     y la variable GROQ_API_KEY
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from observability.safety import count_pii, detect_injection, mask_pii
from observability.tracer import span

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:                       # permite probar el handler sin langchain instalado
    BaseCallbackHandler = object

INSTRUCCIONES = """Eres 'SupportOps', un agente de soporte técnico.
Reglas:
1. Para registrar un ticket necesitas: usuario, departamento, descripción y prioridad.
2. Si faltan datos, NO crees el ticket. Pide los datos faltantes amablemente.
3. Cuando tengas todos los datos, ejecuta 'registrar_ticket'."""


@dataclass(frozen=True)
class SupportConfig:
    temperature: float
    max_retries: int | None     # None = valor por defecto de la librería (como en la EP2)
    timeout_s: float | None
    max_concurrency: int
    guardrail: bool
    mask_pii: bool
    safe_storage: bool
    max_input_chars: int        # 0 = sin límite


BASELINE = SupportConfig(0.0, None, None, 64, False, False, False, 0)
OPTIMIZED = SupportConfig(0.0, 4, 30, 3, True, True, True, 1500)


# ------------------------------------------------------------------ validación de datos
PRIORIDADES = ["Alta", "Media", "Baja"]
PLACEHOLDERS = {"", "?", "??", "n/a", "na", "none", "null", "desconocido", "unknown", "no especificado", "sin datos"}


def normalize_priority(p: str) -> str | None:
    """'Alt.a' -> 'Alta', 'bja' -> 'Baja'. None si no se reconoce."""
    import difflib
    cleaned = re.sub(r"[^a-záéíóúñ]", "", (p or "").lower()).capitalize()
    if cleaned in PRIORIDADES:
        return cleaned
    m = difflib.get_close_matches(cleaned, PRIORIDADES, n=1, cutoff=0.6)
    return m[0] if m else None


def missing_fields(usuario: str, departamento: str, descripcion: str, prioridad: str) -> list[str]:
    vals = {"usuario": usuario, "departamento": departamento, "descripcion": descripcion}
    bad = [k for k, v in vals.items() if (v or "").strip().lower() in PLACEHOLDERS]
    if normalize_priority(prioridad) is None:
        bad.append("prioridad (Alta, Media o Baja)")
    return bad


# ------------------------------------------------------------------ herramientas
def make_tools(path: str | Path, safe: bool, mask: bool):
    from langchain_core.tools import tool
    path = Path(path)
    lock = threading.Lock()

    @tool
    def registrar_ticket(usuario: str, departamento: str, descripcion: str, prioridad: str) -> str:
        """Registra un ticket de soporte. Requiere: usuario, departamento, descripcion y prioridad."""
        if safe:                                         # capa de validación determinista (antes de escribir)
            faltan = missing_fields(usuario, departamento, descripcion, prioridad)
            if faltan:
                return "ERROR: faltan o son inválidos estos datos: " + ", ".join(faltan) + ". Pídelos al usuario; NO inventes valores."
            prioridad = normalize_priority(prioridad)
        suffix = f"-{uuid.uuid4().hex[:4]}" if safe else ""
        ticket_id = f"TCK-{datetime.now().strftime('%Y%m%d%H%M%S')}{suffix}"
        data = {"ticket_id": ticket_id, "usuario": mask_pii(usuario) if mask else usuario, "departamento": departamento,
                "descripcion": mask_pii(descripcion) if mask else descripcion,
                "prioridad": prioridad, "estado": "Abierto"}

        def _append():
            tickets = []
            if path.exists():
                try:
                    tickets = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    tickets = []
            tickets.append(data)
            if safe:                                     # escritura atómica
                fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(tickets, f, indent=4, ensure_ascii=False)
                os.replace(tmp, path)
            else:                                        # igual que en la EP2
                path.write_text(json.dumps(tickets, indent=4, ensure_ascii=False), encoding="utf-8")

        path.parent.mkdir(parents=True, exist_ok=True)
        if safe:
            with lock:
                _append()
        else:
            _append()
        return f"ÉXITO: Ticket creado con ID {ticket_id} y prioridad {prioridad}."

    @tool
    def consultar_politicas_internas(consulta: str) -> str:
        """Consulta normativas de TI/RRHH sobre VPN, hardware o contraseñas."""
        politicas = {"vpn": "Políticas VPN: Requiere MFA. Prioridad Alta.",
                     "hardware": "Políticas Hardware: Requiere aprobación. Prioridad Media."}
        for clave, pol in politicas.items():
            if clave in consulta.lower():
                return pol
        return "Política general: Generar ticket con prioridad Media."

    return [registrar_ticket, consultar_politicas_internas]


# ------------------------------------------------------------------ trazabilidad
class TraceHandler(BaseCallbackHandler):
    """Convierte los eventos de LangChain/LangGraph en spans del Trace activo."""

    def __init__(self, t):
        self.t = t
        self._starts: dict = {}

    def _start(self, run_id, name, **attrs):
        self._starts[run_id] = (time.perf_counter(), name, attrs)

    def _end(self, run_id, status="ok", error=None):
        st = self._starts.pop(run_id, None)
        if not st:
            return
        t0, name, attrs = st
        attrs = {k: v for k, v in attrs.items() if not k.startswith("_")}
        self.t.spans.append({"name": name, "status": status, "error": error, "retries": 0,
                             "ms": round((time.perf_counter() - t0) * 1000, 2), **attrs})
        if status == "error":
            self.t.error_step, self.t.error_type = name, error

    # LLM
    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        self._start(run_id, "llm")

    def on_llm_start(self, serialized, prompts, *, run_id, **kw):
        self._start(run_id, "llm")

    def on_llm_end(self, response, *, run_id, **kw):
        tin = tout = 0
        try:
            u = response.generations[0][0].message.usage_metadata or {}
            tin, tout = u.get("input_tokens", 0), u.get("output_tokens", 0)
        except Exception:
            u = (getattr(response, "llm_output", None) or {}).get("token_usage", {})
            tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        self.t.add_tokens(tin, tout)
        self._end(run_id)

    def on_llm_error(self, error, *, run_id, **kw):
        self._end(run_id, "error", type(error).__name__)

    # Herramientas: tools_called cuenta solo ejecuciones EXITOSAS; los intentos fallidos
    # (p. ej. argumentos incompletos rechazados por la validación) quedan como span 'tool' con error.
    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        name = (serialized or {}).get("name") or kw.get("name") or "tool"
        self.t.attrs["tool_attempts"] = self.t.attrs.get("tool_attempts", 0) + 1
        self._start(run_id, "tool", tool=name, _args=str(kw.get("inputs") or input_str))

    def on_tool_end(self, output, *, run_id, **kw):
        out = str(getattr(output, "content", output))
        if out.startswith("ERROR"):                      # la herramienta rechazó los datos: no es un éxito
            self._end(run_id, "error", "ToolRejected")
            return
        st = self._starts.get(run_id)
        if st:
            self.t.tools_called.append(st[2].get("tool", "tool"))
            self.t.tool_args.append(st[2].get("_args", ""))
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kw):
        self._end(run_id, "error", type(error).__name__)


def decision_signature(t) -> str:
    """Firma de la decisión: herramientas usadas + prioridad elegida (para medir consistencia)."""
    prio = ""
    for a in t.tool_args:
        m = re.search(r"prioridad['\"]?\s*[:=]\s*['\"]?(\w+)", a.lower())
        if m:
            prio = m.group(1)
    return ",".join(sorted(t.tools_called)) + "|" + prio


# ------------------------------------------------------------------ agente
class SupportOpsAgent:
    def __init__(self, cfg: SupportConfig, tickets_path: str | Path, model: str | None = None, agent=None):
        self.cfg = cfg
        self.tickets_path = Path(tickets_path)
        self._slots = threading.Semaphore(cfg.max_concurrency)
        if agent is not None:                       # inyección para pruebas
            self.agent = agent
            return
        from langchain_groq import ChatGroq
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.prebuilt import create_react_agent
        kw = {"model": model or os.environ.get("LLM_MODEL", "openai/gpt-oss-20b"), "temperature": cfg.temperature}
        if cfg.max_retries is not None:
            kw["max_retries"] = cfg.max_retries
        if cfg.timeout_s:
            kw["timeout"] = cfg.timeout_s
        llm = ChatGroq(**kw)                        # usa la variable GROQ_API_KEY
        tools = make_tools(self.tickets_path, cfg.safe_storage, cfg.mask_pii)
        self.agent = create_react_agent(llm, tools, prompt=INSTRUCCIONES, checkpointer=MemorySaver())

    def run(self, t, query: str, thread_id: str) -> str:
        if self.cfg.guardrail:
            with span("guardrail"):
                if detect_injection(query):
                    t.mark_blocked("prompt_injection")
                    t.set_output("No puedo ayudar con esa solicitud.")
                    t.set_signature("blocked")
                    return t.output
        text = mask_pii(query) if self.cfg.mask_pii else query
        if self.cfg.max_input_chars and len(text) > self.cfg.max_input_chars:
            h = self.cfg.max_input_chars // 2
            text = text[:h] + " … " + text[-h:]
        t.attrs["pii_to_llm"] = count_pii(text)
        handler = TraceHandler(t)
        with self._slots:
            result = self.agent.invoke({"messages": [("user", text)]},
                                       config={"configurable": {"thread_id": thread_id}, "callbacks": [handler]})
        out = result["messages"][-1].content
        if isinstance(out, list):
            out = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in out)
        t.set_output(out)
        t.set_signature(decision_signature(t))
        return out
