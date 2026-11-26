"""Seguridad y uso responsable: enmascarado de PII, detección de inyección de prompt,
y hash con sal de las entradas (los logs NUNCA guardan el texto original del usuario).

Alineado con: Ley 19.628 / Ley 21.719 (Chile, minimización de datos), OWASP Top 10 LLM.
"""
from __future__ import annotations

import hashlib
import os
import re

# --- PII (patrones orientados a Chile) -------------------------------------
_PII_PATTERNS = [
    ("RUT", re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("TEL", re.compile(r"(?<![\w.])(?:\+?56[\s-]?)?9[\s-]?\d{4}[\s-]?\d{4}(?![\w])")),
    ("TARJETA", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
]


def mask_pii(text: str) -> str:
    """Reemplaza PII por marcadores [RUT], [EMAIL], etc."""
    if not text:
        return text
    for label, rx in _PII_PATTERNS:
        text = rx.sub(f"[{label}]", text)
    return text


def count_pii(text: str) -> int:
    """Cuenta coincidencias de PII (sirve para auditar que los logs estén limpios)."""
    return sum(len(rx.findall(text or "")) for _, rx in _PII_PATTERNS)


# --- Inyección de prompt -----------------------------------------------------
_INJECTION = re.compile(
    r"(ignora (todas )?(las )?(instrucciones|reglas)|olvida (tus|las) instrucciones|"
    r"ignore (all |previous )?instructions|system prompt|prompt del sistema|"
    r"act[uú]a como|eres ahora|developer mode|revela (tu|el) prompt|"
    r"muestra (la |las |el |los )?(claves?|contrase[ñn]as?|api[ _-]?key))",
    re.IGNORECASE,
)


def detect_injection(text: str) -> bool:
    return bool(_INJECTION.search(text or ""))


# --- Pseudonimización --------------------------------------------------------
_SALT = os.environ.get("OBS_SALT", "cambia-esta-sal-en-produccion")


def hash_text(text: str) -> str:
    """SHA-256 con sal, truncado. Permite agrupar repeticiones sin almacenar el texto."""
    return hashlib.sha256((_SALT + (text or "")).encode("utf-8")).hexdigest()[:16]


# --- Herramientas permitidas (mínimo privilegio) ----------------------------
ALLOWED_TOOLS = {"consulta_estado_tramite", "buscar_faq"}


def tool_allowed(name: str) -> bool:
    return name in ALLOWED_TOOLS
