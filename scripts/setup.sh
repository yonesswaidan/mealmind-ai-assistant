#!/usr/bin/env bash
# Installerer afhængigheder og bygger frontend. Kør én gang (og efter opdateringer).
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3.13 python3.14 python3.12 python3; do
    if command -v "$candidate" >/dev/null; then PY="$candidate"; break; fi
  done
fi
echo "Bruger $PY"

[ -d backend/.venv ] || "$PY" -m venv backend/.venv
backend/.venv/bin/pip install -q --upgrade pip
backend/.venv/bin/pip install -q -r backend/requirements-dev.txt

(cd frontend && npm ci && npm run build)

[ -f .env ] || { cp .env.example .env; echo "Oprettede .env - indsæt OPENAI_API_KEY."; }
echo "Klar. Start med: scripts/start.sh"
