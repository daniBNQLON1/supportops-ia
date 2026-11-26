#!/usr/bin/env bash
# Reproduce todo el flujo: logs -> métricas/análisis -> dashboard -> pruebas -> informe
set -euo pipefail
python3 -m scripts.run_experiments --mode baseline  --out data/logs/baseline.jsonl
python3 -m scripts.run_experiments --mode optimized --out data/logs/optimized.jsonl
python3 -m scripts.analyze --logs data/logs/baseline.jsonl data/logs/optimized.jsonl
python3 -m scripts.build_dashboard
python3 -m pytest -q tests --junitxml=reports/pytest_results.xml
python3 -m scripts.make_report
echo "Listo: abra dashboard/index.html y reports/Informe_EP3.docx"
