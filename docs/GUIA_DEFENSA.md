# Guía de defensa — SupportOps (datos reales de TU corrida)

Cifras: baseline = agente de la EP2 sin cambios; optimizado = con las correcciones. 76 turnos por corrida (modo rápido), 8 escenarios.
Resumen: precisión 89,5 % → 96,1 %; errores 9,2 % → 3,9 %; PII enviada al LLM 8 → 0; PII guardada en tickets 2 → 0.

## Estructura sugerida (10 min)
1. Qué agente es (LangGraph + Groq, 2 herramientas, memoria) y los 8 escenarios (1 min)
2. Métricas y por qué esas (2 min) · 3. Hallazgos en logs (3 min) · 4. Correcciones y resultados (2 min) · 5. Ética/privacidad (1 min) · 6. Limitaciones y escalabilidad (1 min)

## Los hallazgos, uno por uno (cómo lo descubrimos → causa → solución → resultado)
| # | Hallazgo | Evidencia | Causa | Solución | Resultado |
|---|---|---|---|---|---|
| 1 | Errores de límite de tasa (RateLimitError / HTTP 429) | 7 errores en el baseline, precisión en ráfaga 50 % | Varias peticiones simultáneas superan el límite del proveedor y no hay reintentos efectivos | 4 reintentos con espera, timeout de 30 s y máximo 3 llamadas simultáneas | 3 errores, ráfaga 75 %. **Mejoró pero no se resolvió.** |
| 2 | Ticket creado con "?" en todos los campos | Auditoría del archivo de tickets: 1 ticket inválido | El modelo rellenó con "?" para pasar la validación de esquema; rompe la regla 2 de las instrucciones | Validación determinista dentro de la herramienta: rechaza vacíos/"?"/N/A y obliga a pedir el dato | 1 → 0 |
| 3 | El modelo intenta usar la herramienta sin todos los datos | Smoke test: span `tool` de 1,4 ms con error | La regla 2 solo se cumplía porque LangChain rechazaba los argumentos incompletos | Mismo punto 2 + medir solo ejecuciones exitosas | Intento fallido queda como error de `tool`, no como éxito |
| 4 | Datos personales enviados al LLM y guardados | 8 PII en prompts; 2 tickets con correo como "usuario" | No había minimización de datos | `mask_pii` (RUT, correo, teléfono, tarjeta) antes del LLM y antes de guardar | 8 → 0 y 2 → 0 |
| 5 | IDs duplicados y riesgo de perder tickets | 1 ID duplicado; en una corrida previa 30 creados vs 29 guardados | ID con resolución de 1 segundo; lectura-modificación-escritura sin lock | Lock + archivo temporal atómico + sufijo único | 0 duplicados, 0 perdidos |
| 6 | Prioridad no estándar ("Alt.a", "Bja") | 2 tickets | No se valida la prioridad | Normalización a Alta/Media/Baja | 2 → 0 |
| 7 | Inyecciones de prompt | El modelo las rechazó solo (6/6), pero cada una costó p95 3,4 s | Sin control previo | Guardrail determinista antes del LLM | 6 bloqueos en 0 ms |
| 8 | Memoria entre turnos | Escenario `incomplete_then_complete`: 92 % → 100 % | Preguntas al usuario por datos que ya había dado | (No fue un cambio de memoria: es variabilidad del LLM) | Con n=12 la diferencia es de 1 turno |

Dos errores **de nuestra propia medición** que detectamos y corregimos (úsalos: muestran rigor):
- Contábamos un intento fallido de herramienta como "uso de herramienta". Ahora solo cuentan las ejecuciones exitosas.
- La auditoría de PII contaba el ID del ticket (14 dígitos) como si fuera una tarjeta: 51 falsos positivos. Ahora solo mira los campos de texto.

## Preguntas probables
**¿Por qué p95 y no el promedio?** El promedio oculta la cola. Aquí p50 = 2,3 s pero p95 = 13,5 s: el usuario que cae en la cola espera seis veces más.
**¿Cómo mide la precisión si el LLM redacta distinto cada vez?** No comparo texto: comparo la decisión. `TOOL:registrar_ticket` (usó la herramienta), `NOTOOL` (no la usó si faltaban datos) o una frase clave. Un error cuenta como incorrecto.
**¿Y la consistencia?** Mismo input repetido 3 veces; mido si la decisión (herramienta + prioridad) coincide. Salió 100 % en complete, policy y burst.
**¿Qué es una traza y un span?** Una traza es un turno completo; un span es una etapa medida (guardrail, llm, tool). Los registra un callback de LangChain.
**¿Por qué 100 % del tiempo está en `llm`?** Las herramientas son locales (ms); casi todo es la llamada al proveedor. Por eso la latencia depende de él y de sus límites.
**¿Por qué la optimizada no cumple los SLO?** Sigue con 3 errores 429 y p95 de 13,7 s en la ráfaga. Reintentos y límite de concurrencia ayudan, pero la solución de fondo es una cola con control de tasa o un plan de pago con más cupo. Los SLO los definimos nosotros.
**¿El guardrail protegió algo, si el modelo ya rechazaba?** Honestamente: no cambió el resultado, pero evita gastar tokens y 3 s por ataque y no depende de que el modelo se porte bien.
**¿Qué es la memoria del agente?** `MemorySaver` guarda el historial por `thread_id` en RAM. Sirve en la sesión, se pierde al reiniciar; en producción iría a SQLite/Postgres.
**¿Qué harías con 10 veces más tráfico?** Cola con control de tasa, varios proveedores o cupo de pago, base de datos real para tickets, caché de políticas, alertas por SLO.
**¿Qué limitaciones tiene el estudio?** Modo rápido, n pequeño por escenario (6 a 18 turnos), una sola corrida, LLM no determinista. La diferencia de memoria (5,9 vs 4,7 MB/100) es ruido de calentamiento.
**¿Cómo cumple privacidad?** Minimización (PII enmascarada antes del proveedor y antes de guardar), logs sin texto del usuario (hash con sal), mínimo privilegio, Ley 19.628 y Ley 21.719 (vigente desde el 1-dic-2026). Falta definir retención de logs y canal de reclamos.
**¿Cuál fue tu aporte?** (Respóndelo tú, con tus palabras.)
