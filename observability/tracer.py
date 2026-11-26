"""Trazabilidad ligera para agentes de IA (compatible con cualquier framework).

Uso:
    from observability.tracer import Tracer, span

    tracer = Tracer("data/logs/mi_agente.jsonl", run_label="baseline")

    with tracer.trace(scenario="normal", input_text=pregunta, expected="clave") as t:
        with span("retrieve"):
            docs = buscar(pregunta)
        with span("llm"):
            respuesta, tin, tout = llamar_llm(pregunta, docs)
            t.add_tokens(tin, tout)
        t.set_output(respuesta)

Cada `trace` escribe UNA línea JSON (JSONL) con latencia total, spans por etapa,
errores clasificados, tokens, CPU, memoria y correctitud. Nunca guarda el texto crudo
del usuario: sólo hash + largo + versión enmascarada truncada de la salida.
"""
from __future__ import annotations

import contextvars
import json
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .safety import hash_text, mask_pii

_current: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("trace", default=None)
_proc = psutil.Process()


def normalize(text: str) -> str:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


class Trace:
    def __init__(self, tracer: "Tracer", scenario: str, input_text: str,
                 expected: str | None, attrs: dict):
        self.tracer = tracer
        self.id = uuid.uuid4().hex[:12]
        self.scenario = scenario
        self.input_hash = hash_text(input_text)
        self.input_len = len(input_text or "")
        self.expected = expected
        self.attrs = attrs
        self.spans: list[dict] = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.output = ""
        self.tools_called: list[str] = []
        self.tool_args: list[str] = []
        self.signature: str | None = None   # firma de decisión (herramientas + parámetros) para medir consistencia
        self.status = "ok"           # ok | error | blocked
        self.error_type: str | None = None
        self.error_step: str | None = None

    def add_tokens(self, tin: int, tout: int) -> None:
        self.tokens_in += int(tin)
        self.tokens_out += int(tout)

    def set_output(self, text: str) -> None:
        self.output = text or ""

    def set_signature(self, sig: str) -> None:
        self.signature = sig

    def mark_blocked(self, reason: str) -> None:
        self.status = "blocked"
        self.error_type = reason


class Tracer:
    def __init__(self, path: str | Path, run_label: str = "default"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_label = run_label
        self._lock = threading.Lock()

    def reset(self) -> None:
        self.path.write_text("")

    @contextmanager
    def trace(self, scenario: str, input_text: str, expected: str | None = None, **attrs):
        t = Trace(self, scenario, input_text, expected, attrs)
        token = _current.set(t)
        t0 = time.perf_counter()
        cpu0 = time.thread_time()
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        try:
            yield t
        except Exception as exc:  # el error queda registrado y se re-lanza al llamador
            if t.status == "ok":
                t.status = "error"
                t.error_type = t.error_type or type(exc).__name__
            raise
        finally:
            _current.reset(token)
            latency_ms = (time.perf_counter() - t0) * 1000
            cpu_ms = (time.thread_time() - cpu0) * 1000
            correct = None
            if expected is not None:
                if expected == "BLOCKED":
                    correct = t.status == "blocked"
                elif expected.startswith("TOOL:"):          # debe haber usado esa herramienta
                    correct = t.status == "ok" and expected[5:] in t.tools_called
                elif expected == "NOTOOL":                  # no debe haber ejecutado herramientas
                    correct = t.status in ("ok", "blocked") and not t.tools_called
                else:
                    correct = t.status == "ok" and normalize(expected) in normalize(t.output)
            rec = {
                "trace_id": t.id, "ts": ts, "run": self.run_label,
                "scenario": scenario, "input_hash": t.input_hash, "input_len": t.input_len,
                "status": t.status, "error_type": t.error_type, "error_step": t.error_step,
                "latency_ms": round(latency_ms, 2), "cpu_ms": round(cpu_ms, 2),
                "rss_mb": round(_proc.memory_info().rss / 1e6, 2),
                "tokens_in": t.tokens_in, "tokens_out": t.tokens_out,
                "expected": expected, "correct": correct,
                "output_hash": hash_text(t.signature if t.signature is not None else normalize(t.output)),
                "tools_called": t.tools_called,
                "output_masked": mask_pii(t.output)[:160],
                "spans": t.spans, **t.attrs,
            }
            with self._lock, self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@contextmanager
def span(name: str, **attrs):
    """Mide una etapa del flujo. Si no hay trace activo, es un no-op."""
    t = _current.get()
    if t is None:
        yield {}
        return
    rec = {"name": name, "status": "ok", "error": None, "retries": 0, **attrs}
    t0 = time.perf_counter()
    try:
        yield rec
    except Exception as exc:
        rec["status"] = "error"
        rec["error"] = type(exc).__name__
        t.error_type = type(exc).__name__
        t.error_step = name
        t.status = "error"
        raise
    finally:
        rec["ms"] = round((time.perf_counter() - t0) * 1000, 2)
        t.spans.append(rec)
