"""Prueba rápida del proveedor LLM configurado (1 llamada).   python -m scripts.check_gemini"""
import os
import sys

from agent.faq_agent import OPTIMIZED, FAQAgent

prov = os.environ.get("LLM_PROVIDER", "gemini").lower()
if prov == "gemini" and not os.environ.get("GEMINI_API_KEY"):
    sys.exit('Falta la clave. En PowerShell:  $env:GEMINI_API_KEY="su_clave"')
ag = FAQAgent(OPTIMIZED)
print(f"Proveedor: {ag.provider} · modelo: {ag.model}")
try:
    text, tin, tout, _ = ag._call_llm("Responde en una frase.", "Di hola en español.")
    print(f"OK · respuesta: {text!r} · tokens {tin}+{tout}")
except Exception as e:
    print(f"ERROR ({type(e).__name__}): {e}")
    print("HTTP404: modelo inexistente (cambie GEMINI_MODEL / LLM_MODEL). HTTP400/401/403: clave o permisos. HTTP429: espere 1 minuto.")
    print("Si es Ollama y dice NetworkError: ¿está abierto Ollama y descargó el modelo?  (ollama pull llama3.2:3b)")
