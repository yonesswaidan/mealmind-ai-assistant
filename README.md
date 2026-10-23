# MealMind AI Data Assistant

Selvstændig hjemmeside, hvor man stiller spørgsmål om MealMind på almindeligt dansk og får svar med
**SQL-forespørgsler, statistiske analyser, ML-modeller, grafer, tabeller og forklaringer**.
Projektet er helt adskilt fra MealMind-appen og deler hverken kode, database eller backend med den.

> **DEMODATA:** Indtil de rigtige Azure Databricks-datasæt er tilgængelige, kører assistenten på to
> syntetiske datasæt (`meal_events`, `pantry_items`). Det vises tydeligt i UI'et, i datasættenes
> beskrivelse og i AI'ens svar.

## Sådan virker det

```
Browser (React)  ──SSE──▶  FastAPI  ──▶  AI-agent (function calling)
                                         ├─ run_sql      → SQL-guard → read-only DB (DuckDB / Databricks)
                                         ├─ analyze_data → pandas-statistik (ingen vilkårlig kode)
                                         ├─ run_ml       → ML-registry (scikit-learn + Databricks Model Serving)
                                         ├─ create_chart → graf-spec til frontend
                                         └─ show_table   → tabel til frontend
```

- **Agenten vælger selv** værktøjer ud fra spørgsmålet. Der er ingen hardcodede svar: skemaet
  (tabeller, kolonner, typer, eksempelværdier) introspekteres fra databasen ved opstart og gives til
  modellen, som skriver SQL og vælger analyser/modeller.
- Hvert trin streames live til UI'et, som viser den udførte SQL, ML-nøgletal, grafer og tabeller.
- AI-provider: **OpenAI Responses API** som standard (`AI_PROVIDER=openai`, model `gpt-6.1-sol`, medium
  reasoning effort). Anthropic kan vælges med `AI_PROVIDER=anthropic`. Model og effort sættes i `.env`.
- Samtaler med OpenAI er stateless (`store=False`): hele samtalen sendes med hver tur, og modellens krypterede
  reasoning sendes retur mellem værktøjskald. API-nøgler læses kun af backend og sendes aldrig til browseren.

### ML-funktioner

| Funktion | Bruges til |
|---|---|
| `forecast_timeseries` | Prognose (lineær trend + sæson) med backtest og ≈95%-interval |
| `segment_clusters` | Segmentering af fx brugere (KMeans, automatisk valg af antal) |
| `detect_anomalies` | Usædvanlige dage/værdier (robust z-score) |
| `predict_outcome` | Klassifikationsmodel for binære udfald (fx madspild) med AUC og feature-betydning |
| `endpoint_*` | Eksisterende modeller i Databricks Model Serving (`DATABRICKS_ML_ENDPOINTS`) |

## Kom i gang lokalt

Kræver Python 3.12–3.14 og Node 20+.

```bash
scripts/setup.sh          # installerer alt, bygger frontend og opretter .env
# indsæt OPENAI_API_KEY i .env
scripts/start.sh          # åbn http://localhost:8000
```

Udvikling med hot reload: `scripts/dev.sh` (frontend på http://localhost:5173, backend på :8000).

## Tests

```bash
scripts/test.sh
```

Kører backend-tests (pytest: SQL-sikkerhed, read-only forbindelse, tools, ML, agent-loop, API, SDK-format),
frontend-tests (vitest), lint, typecheck og produktionsbuild. En scriptet test-LLM
(`ASSISTANT_TEST_MODE=1`) bruges til end-to-end-tests uden API-nøgle; den bruges aldrig i drift.

## Forbind til Azure Databricks

1. Opret en service principal (eller et token) med **kun læseadgang**:
   ```sql
   GRANT USE CATALOG ON CATALOG main TO `mealmind-assistant`;
   GRANT USE SCHEMA ON SCHEMA main.mealmind TO `mealmind-assistant`;
   GRANT SELECT ON TABLE main.mealmind.<tabel1> TO `mealmind-assistant`;
   GRANT SELECT ON TABLE main.mealmind.<tabel2> TO `mealmind-assistant`;
   ```
   og giv den `CAN USE` på SQL Warehouse'et.
2. Udfyld i `.env`:
   ```
   DATA_SOURCE=databricks
   DATABRICKS_SERVER_HOSTNAME=adb-....azuredatabricks.net
   DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/...
   DATABRICKS_TOKEN=...
   DATABRICKS_TABLES=main.mealmind.<tabel1>,main.mealmind.<tabel2>
   ```
3. Undersøg datasættene: `cd backend && .venv/bin/python -m app.inspect_data`
   (kolonner, typer, null-andele, antal unikke værdier og eksempler).
4. Genstart. Tilføj gerne kolonne- og tabelkommentarer i Unity Catalog – de vises for AI'en og forbedrer svarene.

## Sikkerhed

AI-genereret SQL passerer flere uafhængige lag:

1. **SQL-guard** (`backend/app/security/sql_guard.py`, sqlglot): præcis én `SELECT`/`WITH`-sætning,
   ingen DDL/DML/`SET`/`COPY`/`ATTACH` osv., kun tabeller fra allowlisten, ingen filstier eller
   tabel-funktioner, ingen farlige funktioner (`read_*`, `getenv`, `reflect`, `java_method`, `secret`, …),
   og `LIMIT` håndhæves altid.
2. **Read-only forbindelse:** DuckDB åbnes `read_only` uden ekstern fil-/netværksadgang og med låst
   konfiguration; Databricks-identiteten må kun læse (se ovenfor).
3. **Timeout** på forespørgsler og rækkegrænse på resultater.
4. API: valgfrit adgangstoken (`APP_ACCESS_TOKEN`), rate limit, CORS-allowlist, sikkerhedsheaders (CSP m.m.).
   API-nøgler og Databricks-token ligger kun på serveren.

Analyser og ML kører som foruddefinerede funktioner – modellen kan ikke køre vilkårlig Python.

## Hosting

```bash
docker compose up --build      # bygger frontend + backend til ét image, http://localhost:8000
```

Ved offentlig hosting: sæt `APP_ACCESS_TOKEN`, `CORS_ORIGINS` til domænet og kør bag HTTPS
(fx Azure Container Apps eller App Service med containeren). Hemmeligheder sættes som miljøvariabler,
ikke i imaget.

## Mappestruktur

```
backend/app/
  agent/       agent-loop, system-prompt, OpenAI- og Anthropic-klient, test-LLM
  data/        demodata-generator og datakilder (DuckDB / Databricks)
  security/    SQL-guard
  tools/       SQL, analyse, ML-registry, grafer/tabeller
  inspect_data.py  profilering af datasæt
frontend/src/  React-chat, grafer (Recharts), tabeller, SSE-klient
```
