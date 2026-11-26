"""Genera dashboard/index.html (autocontenido, sin dependencias) desde reports/analysis.json.
    python -m scripts.build_dashboard
"""
import json
from pathlib import Path

d = json.loads(Path("reports/analysis.json").read_text(encoding="utf-8"))
html = Path("dashboard/template.html").read_text(encoding="utf-8").replace("/*DATA*/null", json.dumps(d, ensure_ascii=False))
Path("dashboard/index.html").write_text(html, encoding="utf-8")
print("-> dashboard/index.html")
