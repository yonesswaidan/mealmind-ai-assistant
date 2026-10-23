#!/usr/bin/env bash
# Kører alle automatiske tests: backend (pytest), frontend (vitest), typecheck, lint og produktionsbuild.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && .venv/bin/python -m pytest -q)
(cd frontend && npm test && npx eslint src && npm run build)
echo "Alle tests bestået."
