"""Análisis de logs y trazas (IE3, IE6): cuellos de botella, taxonomía de errores,
anomalías y hallazgos con evidencia. Todo se deriva de los datos; nada está escrito a mano.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import SLO


def explode_spans(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        for s in r["spans"]:
            rows.append({"trace_id": r["trace_id"], "scenario": r["scenario"], "input_len": r["input_len"],
                         "step": s["name"], "ms": s["ms"], "status": s["status"],
                         "error": s.get("error"), "retries": s.get("retries", 0), "ts": r["ts"]})
    return pd.DataFrame(rows)


def step_breakdown(sp: pd.DataFrame) -> pd.DataFrame:
    g = sp.groupby("step")["ms"]
    out = pd.DataFrame({"mean_ms": g.mean(), "p95_ms": g.quantile(.95), "total_ms": g.sum(),
                        "calls": g.size(),
                        "error_rate": sp.assign(e=sp["status"].eq("error")).groupby("step")["e"].mean(),
                        "retries": sp.groupby("step")["retries"].sum()})
    out["share_pct"] = 100 * out["total_ms"] / out["total_ms"].sum()
    return out.sort_values("total_ms", ascending=False).round(2)


def latency_outliers(df: pd.DataFrame, k: float = 3.0) -> pd.DataFrame:
    """Anomalías de latencia por escenario con la regla IQR (Q3 + k·IQR)."""
    res = []
    for sc, g in df.groupby("scenario"):
        q1, q3 = g["latency_ms"].quantile([.25, .75])
        thr = q3 + k * (q3 - q1)
        o = g[g["latency_ms"] > thr]
        if len(o):
            res.append({"scenario": sc, "n_outliers": len(o), "threshold_ms": round(thr, 1),
                        "max_ms": round(o["latency_ms"].max(), 1)})
    return pd.DataFrame(res)


def spearman(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 5 or a.nunique() < 2 or b.nunique() < 2:
        return float("nan")
    return float(a.rank().corr(b.rank()))


def findings(df: pd.DataFrame) -> list[dict]:
    """Reglas que convierten métricas en hallazgos accionables (hipótesis + recomendación)."""
    out: list[dict] = []
    sp = explode_spans(df)
    bd = step_breakdown(sp)

    # 1) Cuello de botella dominante
    top = bd.iloc[0]
    if top["share_pct"] >= 35:
        out.append({"id": "H1", "severity": "alta", "area": "Latencia",
                    "evidence": f"La etapa '{bd.index[0]}' concentra {top['share_pct']:.0f}% del tiempo total "
                                f"(media {top['mean_ms']:.1f} ms, p95 {top['p95_ms']:.1f} ms).",
                    "hypothesis": "Es el cuello de botella: cualquier mejora global debe empezar aquí.",
                    "recommendation": f"Optimizar '{bd.index[0]}': caché, límites de entrada, ejecución paralela o modelo más liviano."})

    # 2) Escalamiento con el tamaño de entrada (por etapa)
    for step, g in sp.groupby("step"):
        rho = spearman(g["input_len"], g["ms"])
        if rho == rho and rho >= 0.6 and g["ms"].mean() >= 5:
            lo = g[g["input_len"] < g["input_len"].median()]["ms"].mean()
            hi = g[g["input_len"] >= g["input_len"].median()]["ms"].mean()
            out.append({"id": f"H2-{step}", "severity": "media", "area": "Escalabilidad",
                        "evidence": f"En '{step}' la latencia crece con el largo de la entrada (Spearman ρ={rho:.2f}; "
                                    f"{lo:.1f} ms → {hi:.1f} ms entre entradas cortas y largas).",
                        "hypothesis": "Costo proporcional (o peor) al tamaño del input: riesgo ante entradas largas/variables.",
                        "recommendation": "Truncar/resumir entradas, fijar tope de tokens y procesar por fragmentos."})

    # 3) Etapas frágiles
    for step, r in bd.iterrows():
        if r["error_rate"] > SLO["error_rate_max"]:
            errs = sp[(sp["step"] == step) & (sp["status"] == "error")]["error"].value_counts().to_dict()
            validation = any("Validation" in str(k) for k in errs)
            out.append({"id": f"H3-{step}", "severity": "alta", "area": "Confiabilidad",
                        "evidence": f"'{step}' falla en {100*r['error_rate']:.1f}% de las llamadas ({errs}).",
                        "hypothesis": ("El LLM invoca la herramienta con argumentos incompletos o inválidos (rechazados por la validación de esquema)."
                                       if validation else "Fallas transitorias de dependencia externa o contención sin reintentos ni backoff."),
                        "recommendation": ("Pedir los datos faltantes ANTES de llamar la herramienta (instrucciones más estrictas, ejemplos few-shot) y validar campos obligatorios en un paso previo."
                                           if validation else "Reintentos con backoff exponencial + jitter, timeouts explícitos, circuit breaker y límite de concurrencia.")})

    # 4) Escenarios con baja precisión o consistencia
    for sc, g in df.groupby("scenario"):
        ev = g[g["correct"].notna()]
        if len(ev) >= 5 and ev["correct"].astype(bool).mean() < SLO["accuracy_min"]:
            out.append({"id": f"H4-{sc}", "severity": "media", "area": "Precisión",
                        "evidence": f"Escenario '{sc}': precisión {100*ev['correct'].astype(bool).mean():.0f}% "
                                    f"(< SLO {100*SLO['accuracy_min']:.0f}%, n={len(ev)}).",
                        "hypothesis": "La variabilidad de datos (ruido, ambigüedad) degrada la recuperación/decisión del modelo.",
                        "recommendation": "Normalizar texto, reducir temperatura, añadir pregunta de aclaración cuando la confianza sea baja."})

    # 5) Fuga de memoria
    from .metrics import rss_slope_per_100
    sl = rss_slope_per_100(df)
    if sl == sl and sl > SLO["rss_slope_mb_per_100req_max"]:
        out.append({"id": "H5", "severity": "alta", "area": "Recursos",
                    "evidence": f"La memoria RSS crece {sl:.1f} MB por cada 100 requests (SLO ≤ {SLO['rss_slope_mb_per_100req_max']}).",
                    "hypothesis": "Estructura que crece sin límite (caché/historial sin política de expulsión).",
                    "recommendation": "Caché con tamaño máximo (LRU) y TTL; no retener documentos completos por request."})

    # 6) Seguridad
    bl = df[df["status"] == "blocked"]
    if len(bl):
        out.append({"id": "H6", "severity": "info", "area": "Seguridad",
                    "evidence": f"El guardrail bloqueó {len(bl)} entradas sospechosas de inyección de prompt.",
                    "hypothesis": "Hay intentos de manipulación; el control funciona y debe monitorearse en el tiempo.",
                    "recommendation": "Alertar si la tasa de bloqueos sube; revisar falsos negativos periódicamente."})
    return out


def error_taxonomy(df: pd.DataFrame) -> pd.DataFrame:
    e = df[df["status"] == "error"]
    if e.empty:
        return pd.DataFrame(columns=["error_step", "error_type", "count"])
    return (e.groupby(["error_step", "error_type"]).size().reset_index(name="count")
            .sort_values("count", ascending=False))
