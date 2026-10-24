#!/usr/bin/env bash
# Starter hele det lokale analysemiljø uden Azure - én kommando:
#   1. MealMind-databasen (read-only snapshot) → pseudonymiseret udtræk → Bronze/Silver/Gold (Delta Lake via
#      delta-rs) → ML (scikit-learn) + lokal MLflow → serving-udtræk. Springes over, hvis kildedata er uændrede.
#   2. MLflow UI på http://localhost:5001
#   3. MealMind Insights på http://localhost:8000 med det lokale lakehouse som datakilde
#
#   scripts/local.sh                  # appens database (biteowl-public/backend/.env DB_PATH, eller MEALMIND_SOURCE_DB)
#   scripts/local.sh --demo           # syntetiske DEMODATA (separat lakehouse, blandes aldrig med rigtige data)
#   scripts/local.sh --refresh        # kør pipelinen igen, selv om kildedata er uændrede
#   scripts/local.sh --no-mlflow-ui   # start ikke MLflow UI
#   scripts/local.sh --pipeline-only  # kør kun pipelinen (ingen servere)
#   scripts/local.sh --engine spark   # Databricks-pipelinens Spark-kode lokalt (kræver Java 17+ og requirements-dev.txt)
#
# Konfiguration (.env eller miljøvariabler): MEALMIND_SOURCE_DB, MEALMIND_SOURCE_ORIGIN, MEALMIND_DATA_PLATFORM,
# MLFLOW_PORT, PORT. Uden MEALMIND_SOURCE_DB følges den database, biteowl-public's backend selv bruger (DB_PATH).
# MEALMIND_SOURCE_ORIGIN=synthetic (standard: udviklingsdatabase med testkonti/syntetiske brugere, lakehouse
# mealmind_devdb) eller real (rigtige brugerdata, lakehouse mealmind - afviser syntetiske udtræk).
# .env's DATA_SOURCE/DATABRICKS_* ændres ikke - lakehouse-kilden gælder kun for denne proces.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

# Læser én nøgle fra .env uden at køre filen som shell-kode (værdier kan indeholde kommentarer).
envval() {
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | tail -1 | sed -e 's/[[:space:]]#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}
setting() { local v="${!1:-}"; [ -n "$v" ] || v="$(envval "$1")"; [ -n "$v" ] || v="$2"; printf '%s' "${v/#\~/$HOME}"; }

DEMO=0; REFRESH=0; MLFLOW_UI=1; SERVERS=1; ENGINE=delta-rs
while [ $# -gt 0 ]; do
  case "$1" in
    --demo) DEMO=1 ;;
    --refresh) REFRESH=1 ;;
    --no-mlflow-ui) MLFLOW_UI=0 ;;
    --pipeline-only) SERVERS=0 ;;
    --engine) ENGINE="${2:?--engine kræver delta-rs eller spark}"; shift ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Ukendt argument: $1 (se scripts/local.sh --help)" >&2; exit 2 ;;
  esac
  shift
done

DP="$(setting MEALMIND_DATA_PLATFORM "$ROOT/../biteowl-public/data-platform")"
SOURCE_DB="$(setting MEALMIND_SOURCE_DB "")"
ORIGIN="$(setting MEALMIND_SOURCE_ORIGIN synthetic)"
MLFLOW_PORT="$(setting MLFLOW_PORT 5001)"
APP_PORT="$(setting PORT 8000)"
case "$ORIGIN" in synthetic|real) ;; *) echo "MEALMIND_SOURCE_ORIGIN skal være synthetic eller real." >&2; exit 2 ;; esac
CATALOG=$([ "$DEMO" = 1 ] && echo mealmind_dev || { [ "$ORIGIN" = synthetic ] && echo mealmind_devdb || echo mealmind; })

if [ ! -d "$DP/mealmind_data" ]; then
  echo "Fandt ikke MealMinds data-platform i $DP." >&2
  echo "Sæt MEALMIND_DATA_PLATFORM i .env til mappen biteowl/data-platform." >&2
  exit 1
fi
DP="$(cd "$DP" && pwd)"
# Uden MEALMIND_SOURCE_DB: brug præcis den SQLite-fil, appens backend bruger (DB_PATH i backend/.env, relativt til
# backend-mappen). Kører appen på PostgreSQL, skal kilden angives eksplicit - URL'en læses ikke ud af appens .env.
APP_BACKEND="$(cd "$DP/.." && pwd)/backend"
if [ "$DEMO" = 0 ] && [ -z "$SOURCE_DB" ] && [ -f "$APP_BACKEND/.env" ]; then
  if grep -q '^DATABASE_URL=..*' "$APP_BACKEND/.env"; then
    echo "Appen bruger PostgreSQL (DATABASE_URL i $APP_BACKEND/.env). Sæt MEALMIND_SOURCE_DB til en read-only URL." >&2
    exit 1
  fi
  APP_DB="$(sed -n 's/^DB_PATH=//p' "$APP_BACKEND/.env" | tail -1 | sed -e 's/[[:space:]]#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  APP_DB="${APP_DB:-./mealmind.db}"
  case "$APP_DB" in /*) SOURCE_DB="$APP_DB" ;; *) SOURCE_DB="$APP_BACKEND/${APP_DB#./}" ;; esac
fi
if [ "$DEMO" = 0 ] && [ -z "$SOURCE_DB" ]; then
  echo "Fandt ikke appens database. Sæt MEALMIND_SOURCE_DB i .env (SQLite-fil eller postgresql://-URL)," >&2
  echo "eller start med syntetiske demodata: scripts/local.sh --demo" >&2
  exit 1
fi

# --- Første gang: virtuelle miljøer og frontend-build -------------------------------------------
if [ ! -x "$DP/.venv/bin/python" ]; then
  PY=""; for c in python3.13 python3.14 python3.12 python3; do command -v "$c" >/dev/null && { PY="$c"; break; }; done
  echo "Opretter data-platformens virtuelle miljø med $PY (kun første gang) ..."
  "$PY" -m venv "$DP/.venv"
  "$DP/.venv/bin/pip" install -q --upgrade pip
  "$DP/.venv/bin/pip" install -q -r "$DP/requirements-local.txt"
fi
if [ "$SERVERS" = 1 ] && { [ ! -x backend/.venv/bin/uvicorn ] || [ ! -f frontend/dist/index.html ]; }; then
  echo "Installerer MealMind Insights (kun første gang) ..."
  scripts/setup.sh
fi

# --- 1. Pipeline: udtræk → Bronze/Silver/Gold → ML + MLflow → serving ---------------------------
ARGS=(local --engine "$ENGINE")
if [ "$DEMO" = 1 ]; then ARGS+=(--demo); else ARGS+=(--source "$SOURCE_DB"); fi
[ "$DEMO" = 0 ] && [ "$ORIGIN" = synthetic ] && ARGS+=(--synthetic)
if [ "$DEMO" = 0 ]; then  # en postgresql://-URL kan indeholde en adgangskode og udskrives derfor aldrig
  case "$SOURCE_DB" in postgres*://*) SHOWN="PostgreSQL (URL skjult)" ;; *) SHOWN="$SOURCE_DB" ;; esac
  echo "▸ Kilde: $SHOWN ($([ "$ORIGIN" = synthetic ] && echo 'udviklingsdata - SYNTETISK' || echo 'rigtige data'))"
fi
[ "$REFRESH" = 1 ] || ARGS+=(--if-changed)
echo "▸ Lokalt lakehouse ($ENGINE, katalog $CATALOG) ..."
LOG="$(mktemp)"; trap 'rm -f "$LOG"' EXIT
(cd "$DP" && MLFLOW_DISABLE_AGENT_HINT=1 .venv/bin/python -W ignore -m mealmind_data "${ARGS[@]}") | tee "$LOG"
SERVING="$(sed -n 's/^SERVING_DIR=//p' "$LOG" | tail -1)"
[ -n "$SERVING" ] || { echo "Pipelinen gav intet serving-udtræk." >&2; exit 1; }
[ "$SERVERS" = 1 ] || exit 0

# --- 2. MLflow UI ---------------------------------------------------------------------------------
MLPID=""; APPPID=""
# Serverne kører som baggrundsjobs, så Ctrl+C/stop (INT/TERM) altid lukker begge - også MLflows workers.
cleanup() {
  rm -f "$LOG"
  for pid in $APPPID $MLPID; do
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if [ "$MLFLOW_UI" = 1 ]; then
  if curl -sf "http://127.0.0.1:$MLFLOW_PORT/health" >/dev/null 2>&1; then
    echo "▸ MLflow UI kører allerede på http://localhost:$MLFLOW_PORT"
  else
    ARTIFACTS="$("$DP/.venv/bin/python" -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).as_uri())' \
      "$DP/.local/mlflow/artifacts")"
    "$DP/.venv/bin/mlflow" server --backend-store-uri "sqlite:///$DP/.local/mlflow/mlflow.db" \
      --default-artifact-root "$ARTIFACTS" --host 127.0.0.1 --port "$MLFLOW_PORT" --workers 1 \
      >"$DP/.local/mlflow/server.log" 2>&1 &
    MLPID=$!
  fi
fi

# --- 3. MealMind Insights -------------------------------------------------------------------------
echo
echo "  MealMind Insights   http://localhost:$APP_PORT"
[ "$MLFLOW_UI" = 1 ] && echo "  MLflow UI           http://localhost:$MLFLOW_PORT   (eksperiment mealmind-local-$CATALOG)"
echo "  Lokalt lakehouse    $DP/.local/lakehouse/$CATALOG"
echo "  Alt kører lokalt - intet sendes til Azure Databricks. Stop med Ctrl+C."
echo
cd backend
DATA_SOURCE=local_export LOCAL_EXPORT_DIR="$SERVING" \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$APP_PORT" &
APPPID=$!
wait "$APPPID"
