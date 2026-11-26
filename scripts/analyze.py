"""Procesa los logs y escribe reports/analysis.json (métricas, desglose por etapa, hallazgos).

    python -m scripts.analyze --logs data/logs/baseline.jsonl data/logs/optimized.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from observability.analysis import (error_taxonomy, explode_spans, findings,
                                     latency_outliers, step_breakdown)
from observability.metrics import compute_all, load_logs, load_slo
from observability.safety import count_pii


def analyze_one(path: str, real: bool = False) -> dict:
    df = load_logs(path)
    sp = explode_spans(df)
    label = str(df["run"].iloc[0])
    ap_ = Path(path).with_name(f"audit_{label}.json")
    return {
        "audit": json.loads(ap_.read_text(encoding="utf-8")) if ap_.exists() else None,
        "label": label,
        "real": real,
        "metrics": compute_all(df),
        "steps": step_breakdown(sp).reset_index().to_dict("records"),
        "errors": error_taxonomy(df).to_dict("records"),
        "outliers": latency_outliers(df).to_dict("records"),
        "findings": findings(df),
        "pii_in_logs": int(df["output_masked"].map(count_pii).sum()),  # auditoría: PII visible en campos de texto del log
        "series": {  # para el dashboard interactivo
            "latency": [[round(r.latency_ms, 1), r.scenario, r.status] for r in df.itertuples()],
            "rss": [round(v, 1) for v in df["rss_mb"]],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", nargs="+", required=True)
    ap.add_argument("--out", default="reports/analysis.json")
    ap.add_argument("--real", action="store_true", help="marca los datos como de agente real (oculta el aviso de demo)")
    ap.add_argument("--slo", help="JSON con SLO propios (ej. slo_real.json)")
    a = ap.parse_args()
    if a.slo:
        load_slo(a.slo)
    res = {r["label"]: r for r in (analyze_one(p, a.real) for p in a.logs)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    for k, v in res.items():
        g = v["metrics"]["global"]
        print(f"{k}: acc={g['accuracy']:.1%} err={g['error_rate']:.1%} p95={g['latency']['p95']:.0f}ms "
              f"cons={g['consistency']:.1%} slope={g['rss_slope_mb_per_100req']:.1f}MB/100req "
              f"PII->LLM={g['pii_to_llm']} PII en logs={v['pii_in_logs']}")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
