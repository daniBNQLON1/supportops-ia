"""Dashboard alternativo en Streamlit (lee directamente los logs JSONL).
    pip install streamlit && streamlit run dashboard/streamlit_app.py
NOTA: el dashboard principal y verificado es dashboard/index.html (sin dependencias).
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observability.analysis import error_taxonomy, explode_spans, findings, step_breakdown  # noqa: E402
from observability.metrics import compute_all, load_logs  # noqa: E402

st.set_page_config(page_title="Observabilidad del agente", layout="wide")
st.title("Observabilidad del agente de IA")
logs = sorted(Path("data/logs").glob("*.jsonl"))
sel = st.sidebar.selectbox("Corrida (log)", logs, format_func=lambda p: p.stem)
df = load_logs(sel)
sc = st.sidebar.multiselect("Escenarios", sorted(df["scenario"].unique()), default=sorted(df["scenario"].unique()))
df = df[df["scenario"].isin(sc)]
m = compute_all(df)["global"]
c = st.columns(5)
c[0].metric("Precisión", f"{100*m['accuracy']:.1f}%")
c[1].metric("Tasa de error", f"{100*m['error_rate']:.1f}%")
c[2].metric("Latencia p95", f"{m['latency']['p95']:.0f} ms")
c[3].metric("Consistencia", f"{100*m['consistency']:.1f}%")
c[4].metric("Memoria", f"{m['rss_slope_mb_per_100req']:.1f} MB/100 req")
l, r = st.columns(2)
l.subheader("Latencia p95 por escenario")
l.bar_chart(df.groupby("scenario")["latency_ms"].quantile(.95))
r.subheader("Tiempo por etapa (%)")
r.bar_chart(step_breakdown(explode_spans(df))["share_pct"])
st.subheader("Memoria RSS (MB)")
st.line_chart(df.reset_index()["rss_mb"])
st.subheader("Latencia por ejecución")
st.scatter_chart(df.reset_index(), x="index", y="latency_ms", color="scenario")
st.subheader("Errores")
st.dataframe(error_taxonomy(df))
st.subheader("Hallazgos")
st.dataframe(pd.DataFrame(findings(df)))
