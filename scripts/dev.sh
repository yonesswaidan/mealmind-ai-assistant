#!/usr/bin/env bash
# Udviklingstilstand: backend med auto-reload på :8000 og Vite med hot reload på http://localhost:5173
set -euo pipefail
cd "$(dirname "$0")/.."
backend/.venv/bin/uvicorn app.main:app --app-dir backend --reload --reload-dir backend/app --port 8000 &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null' EXIT
(cd frontend && npm run dev)
