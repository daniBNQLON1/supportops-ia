"""Agente DEMO (simulado) de atención a usuarios, instrumentado con `observability`.

IMPORTANTE: es un agente sintético para poder ejecutar y validar toda la cadena de
observabilidad sin credenciales ni red. Sirve de ejemplo de cómo instrumentar; para la
evaluación reemplácelo por SU agente (ver docs/ADAPTAR_A_SU_AGENTE.md).

Dos modos:
  optimized=False  "baseline": reproduce problemas típicos (sin timeouts/reintentos, caché sin
                   límite, sin normalización, temperatura alta, PII enviada al LLM).
  optimized=True   aplica las correcciones derivadas del análisis de logs.
"""
from __future__ import annotations

import difflib
import re
import threading
import time
import unicodedata
from collections import OrderedDict

from observability.safety import count_pii, detect_injection, mask_pii, tool_allowed
from observability.tracer import span

# (pregunta canónica, frase clave esperada, respuesta, usa_herramienta)
KB = [
    ("¿Cómo restablezco mi contraseña del portal?", "olvidé mi clave",
     "Para restablecer tu contraseña usa la opción 'olvidé mi clave' y sigue el enlace enviado a tu correo institucional.", False),
    ("¿Cuándo es el plazo para renovar la matrícula?", "plazo de matrícula",
     "El plazo de matrícula vence el último día hábil de enero; puedes pagar en línea.", False),
    ("¿Cómo solicito un certificado de alumno regular?", "certificado de alumno regular",
     "Solicita el certificado de alumno regular en Servicios en Línea; llega en 24 horas.", False),
    ("¿Dónde veo mi horario de clases?", "horario de clases",
     "Tu horario de clases está en Mi Portal > Mi horario.", False),
    ("¿Cómo postulo a una beca de alimentación?", "beca de alimentación",
     "Postula a la beca de alimentación en el formulario de Asuntos Estudiantiles antes del 30 de abril.", False),
    ("¿Cuál es el estado de mi trámite de convalidación?", "estado del trámite",
     "El estado del trámite de convalidación es: en revisión.", True),
    ("¿Cuál es el horario de la biblioteca?", "horario de la biblioteca",
     "El horario de la biblioteca es de lunes a viernes de 8:00 a 21:00.", False),
    ("¿Cómo inscribo mi práctica profesional?", "práctica profesional",
     "Inscribe tu práctica profesional con el coordinador de carrera y sube el formulario al portal.", False),
    ("¿Cómo me conecto al wifi del campus?", "wifi del campus",
     "Para el wifi del campus conéctate a Campus-Wifi con tus credenciales institucionales.", False),
    ("¿Cómo pago mi arancel en cuotas?", "arancel en cuotas",
     "Puedes pagar tu arancel en cuotas desde Pagos en Línea, hasta en 10 cuotas.", False),
]
FALLBACK = "No tengo información suficiente para responder; te derivo a un ejecutivo."

_STOP = set("de la el mi mis del al en a un una como cual cuando donde que es y me con para por lo los las se su sus tu tus o u si no mas muy ya hay le les".split())


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zñ]+", strip_accents(text.lower())) if w not in _STOP and len(w) > 2]


KB_TOK = [set(tokens(q)) for q, *_ in KB]
VOCAB = sorted(set().union(*KB_TOK))

_LLM_SLOTS = threading.Semaphore(4)       # capacidad concurrente del proveedor LLM (simulada)
_LEAK: list[bytes] = []                   # baseline: caché sin límite (fuga deliberada)
_LRU: "OrderedDict[str, tuple]" = OrderedDict()
_LRU_MAX = 16
_lock = threading.Lock()


class DemoAgent:
    def __init__(self, optimized: bool = False):
        self.opt = optimized

    # ------------------------------------------------------------------ etapas
    def _guardrail(self, t, query: str) -> bool:
        with span("guardrail"):
            time.sleep(0.001)
            if detect_injection(query):
                t.mark_blocked("prompt_injection")
                t.set_output("No puedo ayudar con esa solicitud.")
                return False
        return True

    def _retrieve(self, query: str):
        with span("retrieve") as sp:
            text = strip_accents(query.lower())
            if self.opt and len(text) > 600:               # límite de entrada: cabeza + cola
                text = text[:300] + " " + text[-300:]
            key = text
            with _lock:
                hit = _LRU.get(key) if self.opt else None
                if hit:
                    _LRU.move_to_end(key)
            if hit:
                sp["cache"] = "hit"
                return hit
            time.sleep(0.004 + 0.000015 * len(text))       # búsqueda vectorial simulada ~ O(largo)
            toks = tokens(text)
            if self.opt:                                    # corrección ortográfica
                toks = [(difflib.get_close_matches(w, VOCAB, n=1, cutoff=0.8) or [w])[0] for w in toks]
            ts = set(toks)
            cands = sorted(((len(ts & k) / len(k), i) for i, k in enumerate(KB_TOK)), key=lambda x: (-x[0], x[1]))
            blob = b"x" * 150_000                           # "documentos" recuperados
            with _lock:
                if self.opt:
                    _LRU[key] = cands
                    while len(_LRU) > _LRU_MAX:
                        _LRU.popitem(last=False)
                else:
                    _LEAK.append(blob)                      # nunca se libera
            sp["cache"] = "miss"
            return cands

    def _llm(self, t, query: str, cands, rng) -> int | None:
        prompt = mask_pii(query) if self.opt else query    # minimización de datos hacia el proveedor
        t.attrs["pii_to_llm"] = count_pii(prompt)
        if self.opt and len(prompt) > 600:
            prompt = prompt[:300] + prompt[-300:]
        with span("llm") as sp:
            max_tries, timeout = (3, 0.5) if self.opt else (1, 0.05)
            tries = 0
            while not _LLM_SLOTS.acquire(timeout=timeout):
                tries += 1
                if tries >= max_tries:
                    raise TimeoutError("LLMTimeout")
                sp["retries"] += 1
                time.sleep(0.01 * 2 ** tries)               # backoff exponencial
            try:
                time.sleep(0.035 + rng.random() * 0.01)
            finally:
                _LLM_SLOTS.release()
            t.add_tokens(len(prompt) // 4 + 200, 60)
            best, second = cands[0], cands[1]
            if best[0] < 0.34:
                return None                                 # sin evidencia: no inventar
            if self.opt:
                return best[1]                              # temperatura 0
            if best[0] - second[0] < 0.4 and rng.random() < 0.45:
                return second[1]                            # temperatura alta: elige el 2.º candidato
            if rng.random() < 0.03:
                return rng.randrange(len(KB))               # alucinación ocasional
            return best[1]

    def _tool(self, rng) -> None:
        with span("tool", tool="consulta_estado_tramite") as sp:
            assert tool_allowed("consulta_estado_tramite")
            attempts = 3 if self.opt else 1
            for a in range(attempts):
                time.sleep(0.02)
                if rng.random() >= 0.25:                    # dependencia externa inestable (25% 503)
                    return
                if a < attempts - 1:
                    sp["retries"] += 1
                    time.sleep(0.01 * 2 ** a)
            raise ConnectionError("HTTP503")

    # ------------------------------------------------------------------ entrada
    def run(self, t, query: str, rng) -> str:
        if not self._guardrail(t, query):
            return t.output
        cands = self._retrieve(query)
        idx = self._llm(t, query, cands, rng)
        if idx is None:
            answer = FALLBACK
        else:
            if KB[idx][3]:
                self._tool(rng)
            answer = KB[idx][2]
        with span("postprocess"):
            time.sleep(0.001)
            answer = mask_pii(answer)
        t.set_output(answer)
        return answer
