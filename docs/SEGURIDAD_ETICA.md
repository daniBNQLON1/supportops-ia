# Seguridad, ética y privacidad (IE8)

| Riesgo | Control en el código | Evidencia en el dashboard |
|---|---|---|
| Inyección de prompt (OWASP LLM01) | `safety.detect_injection` + etapa `guardrail` | Escenario `injection`: % bloqueado |
| Fuga de datos personales al proveedor | `mask_pii` antes de llamar al LLM (minimización) | KPI "PII enviada al LLM" |
| Datos personales en logs | Solo `input_hash` (SHA-256 con sal), largo y salida enmascarada | "PII legible en los logs" = 0 |
| Abuso de herramientas | `ALLOWED_TOOLS` (mínimo privilegio) | Spans `tool` |
| Alucinación | Umbral de confianza → derivación a humano | Precisión en escenarios `ambiguous` |
| Disponibilidad | Timeouts, reintentos con backoff, límite de concurrencia | Tasa de error en `burst` |

Marco: Ley 19.628 y Ley 21.719 (vigente desde el 1-dic-2026): finalidad, minimización, seguridad, derechos del titular;
OWASP Top 10 LLM; NIST AI RMF. **Pendiente del equipo:** política de retención de logs, cambiar `OBS_SALT` y guardarla como secreto,
supervisión humana y canal de reclamos. Nota: los patrones de PII/inyección son heurísticos; deben revisarse periódicamente (falsos negativos).
