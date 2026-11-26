"""Cálculo de métricas de observabilidad a partir de logs JSONL.

Métricas (IE1, IE2):
  Precisión / accuracy ..... correct / evaluados (un error cuenta como respuesta incorrecta)
  Consistencia ............. para un mismo input repetido k veces: fracción de corridas que
                             coinciden con la respuesta más frecuente (1.0 = totalmente estable)
  Frecuencia de errores .... status == error / total (los 'blocked' NO son error: son decisión de seguridad)
  Latencia ................. p50 / p95 / p99 / media (ms), total y por etapa
  Uso de recursos .......... CPU (ms de CPU del hilo), memoria RSS y su pendiente (MB / 100 req), tokens
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# Objetivos de nivel de servicio (SLO). Ajústelos a su caso y justifíquelos en el informe.
SLO = {
    "accuracy_min": 0.85,
    "error_rate_max": 0.02,
    "p95_ms_max": 250.0,
    "consistency_min": 0.90,
    "rss_slope_mb_per_100req_max": 5.0,
}


def load_slo(path: str) -> None:
    """Sobrescribe los SLO desde un JSON (ej. slo_real.json). Modifica el dict SLO en el lugar."""
    SLO.update(json.loads(Path(path).read_text(encoding="utf-8")))


def load_logs(path: str | Path) -> pd.DataFrame:
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def accuracy(df: pd.DataFrame) -> float:
    ev = df[df["correct"].notna()]
    return float(ev["correct"].astype(bool).mean()) if len(ev) else float("nan")


def error_rate(df: pd.DataFrame) -> float:
    return float((df["status"] == "error").mean()) if len(df) else float("nan")


def consistency(df: pd.DataFrame) -> float:
    """Acuerdo con la respuesta modal entre repeticiones del mismo input (sólo ejecuciones sin error)."""
    ok = df[df["status"] != "error"]
    scores = []
    for _, g in ok.groupby(["scenario", "input_hash"]):
        if len(g) >= 2:
            scores.append(g["output_hash"].value_counts().iloc[0] / len(g))
    return float(np.mean(scores)) if scores else float("nan")


def latency_stats(s: pd.Series) -> dict:
    if s.empty:
        return {k: float("nan") for k in ("mean", "p50", "p95", "p99", "max")}
    return {"mean": float(s.mean()), "p50": float(s.quantile(.5)), "p95": float(s.quantile(.95)),
            "p99": float(s.quantile(.99)), "max": float(s.max())}


def rss_slope_per_100(df: pd.DataFrame) -> float:
    """Pendiente de la memoria (MB por cada 100 requests) vía regresión lineal. >SLO sugiere fuga."""
    if len(df) < 10:
        return float("nan")
    x = np.arange(len(df))
    return float(np.polyfit(x, df["rss_mb"].to_numpy(), 1)[0] * 100)


def summarize(df: pd.DataFrame) -> dict:
    lat = latency_stats(df["latency_ms"])
    return {
        "n": int(len(df)),
        "accuracy": accuracy(df),
        "error_rate": error_rate(df),
        "blocked": int((df["status"] == "blocked").sum()),
        "consistency": consistency(df),
        "latency": lat,
        "cpu_ms_mean": float(df["cpu_ms"].mean()),
        "rss_mb_max": float(df["rss_mb"].max()),
        "rss_slope_mb_per_100req": rss_slope_per_100(df),
        "pii_to_llm": int(df["pii_to_llm"].fillna(0).sum()) if "pii_to_llm" in df else 0,
        "tokens_mean": float((df["tokens_in"] + df["tokens_out"]).mean()),
        "errors_by_type": df.loc[df["status"] == "error", "error_type"].value_counts().to_dict(),
    }


def compute_all(df: pd.DataFrame) -> dict:
    out = {"global": summarize(df), "by_scenario": {}}
    for sc, g in df.groupby("scenario"):
        out["by_scenario"][sc] = summarize(g)
    g = out["global"]
    out["slo"] = {
        "accuracy": g["accuracy"] >= SLO["accuracy_min"],
        "error_rate": g["error_rate"] <= SLO["error_rate_max"],
        "p95": g["latency"]["p95"] <= SLO["p95_ms_max"],
        "consistency": (g["consistency"] >= SLO["consistency_min"]) if not np.isnan(g["consistency"]) else None,
        "memory": (g["rss_slope_mb_per_100req"] <= SLO["rss_slope_mb_per_100req_max"])
        if not np.isnan(g["rss_slope_mb_per_100req"]) else None,
    }
    out["slo_targets"] = SLO
    return out
