# MealMind AI Data Assistant

Selvstændig hjemmeside, hvor man stiller spørgsmål om MealMind på almindeligt dansk og får svar med
**SQL-forespørgsler, statistiske analyser, ML-modeller, grafer, tabeller og forklaringer**.
Projektet er helt adskilt fra MealMind-appen og deler hverken kode, database eller backend med den.

Datakilder (`DATA_SOURCE`):

| Værdi | Data | Mærkat i UI |
|---|---|---|
| `demo` (standard) | To syntetiske demodatasæt i lokal DuckDB | DEMODATA |
| `local_export` | Et godkendt, pseudonymiseret udtræk af MealMinds rigtige data (fra `biteowl/data-platform`) | Udtræk |
| `databricks` | MealMinds Silver/Gold-tabeller i Azure Databricks via SQL Warehouse | Databricks |

Syntetiske data vises altid som DEMODATA/TESTDATA – også hvis et Databricks-katalog eller udtræk er markeret
som testdata – og AI'en får besked på aldrig at præsentere dem som rigtige brugere.

## Sådan virker det

```
Browser (React)  ──SSE──▶  FastAPI  ──▶  AI-agent (function calling)
                                         ├─ run_sql      → SQL-guard → read-only DB (DuckDB / Databricks)
                                         ├─ analyze_data → pandas-statistik (ingen vilkårlig kode)
                                         ├─ run_ml       → ML-registry (scikit-learn + Databricks Model Serving)
                                         │                 (højst ML_MAX_CALLS_PER_QUESTION kørsler pr. spørgsmål)
                                         ├─ create_chart → graf-spec til frontend
                                         └─ show_table   → tabel til frontend
```

- **Automatisk værktøjsvalg:** en deterministisk router (`backend/app/agent/router.py`) vurderer først, om
  spørgsmålet kræver SQL, statistik, prognose, similarity search, segmentering, afvigelser, klassifikation,
  visualisering – eller en kombination – og om det handler om madspild. Vurderingen vises som "Analyse:"-chips
  i UI'et og gives til modellen som hint. Modellen vælger derefter de konkrete værktøjskald, men kun blandt de
  godkendte værktøjer og ML-funktioner.
- **Ingen opfundne resultater:** alle tal skal komme fra værktøjsresultater. Indeholder et svar tal, uden at der
  er hentet eller beregnet data, vises en advarsel. ML-funktioner afviser for små datasæt med en forklaring,
  og antallet af ML-kørsler pr. spørgsmål er begrænset.
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
| `predict_outcome` | Klassifikationsmodel for binære udfald (fx sprunget måltid) med AUC og feature-betydning |
| `find_similar` | Similarity search: lignende retter/varer ud fra navn og evt. næring (virker med få data) |
| `endpoint_*` | Eksisterende modeller i Databricks Model Serving (`DATABRICKS_ML_ENDPOINTS`) |

Modeller trænet i Databricks (similarity, segmenter, skip-klassifikation, afvigelser) skrives til
`mealmind.gold.*` og læses med almindelig SQL. `gold.ml_model_status` forklarer, hvilke modeller der er trænet,
og hvorfor andre mangler (fx for få brugere, eller at MealMind ikke registrerer madspild).

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

Kører backend-tests (pytest: SQL-sikkerhed, read-only forbindelse, tools, ML, agent-loop, API, SDK-format,
værktøjsvalg, Databricks med mocket SQL Warehouse – token og OAuth – samt lokalt udtræk),
frontend-tests (vitest), lint, typecheck og produktionsbuild. En scriptet test-LLM
(`ASSISTANT_TEST_MODE=1`) bruges til end-to-end-tests uden API-nøgle; den bruges aldrig i drift.

## Forbind til Azure Databricks

Pipelinen, der bygger tabellerne, ligger i `biteowl/data-platform` (eksport → Bronze → Silver → Gold + ML).
Hele opsætningen i Azure Portal og Databricks er beskrevet trin for trin i
`biteowl/data-platform/docs/AZURE_SETUP.md`. Kort:

1. Opret en service principal `mealmind-aida` med **kun læseadgang** (`USE CATALOG`, `USE SCHEMA`, `SELECT` på
   `mealmind.silver` og `mealmind.gold`) og *Can use* på SQL Warehouse'et.
2. Udfyld i `.env`:
   ```
   DATA_SOURCE=databricks
   DATABRICKS_SERVER_HOSTNAME=adb-....azuredatabricks.net
   DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/...
   DATABRICKS_CLIENT_ID=...          # OAuth M2M (anbefalet) – alternativt DATABRICKS_TOKEN
   DATABRICKS_CLIENT_SECRET=...
   DATABRICKS_TABLES=mealmind.silver.*,mealmind.gold.*
   ```
   `catalog.schema.*` finder selv alle tabeller i skemaet (interne `_`-tabeller udelades). Tabel- og
   kolonnekommentarer fra Unity Catalog vises for AI'en.
3. Undersøg datasættene: `cd backend && .venv/bin/python -m app.inspect_data`.
4. Genstart. Sidebaren viser **Databricks**.

### Lokalt udtræk uden Databricks

Et godkendt udtræk fra `biteowl/data-platform` (`python -m mealmind_data export`) kan analyseres direkte:

```
DATA_SOURCE=local_export
LOCAL_EXPORT_DIR=/sti/til/exports       # én batch-mappe eller en mappe med flere (nyeste bruges)
```

AIDA kontrollerer manifestets checksummer og kvalitetsflag, indlæser Parquet-filerne i en read-only DuckDB og
markerer data som testdata, hvis manifestet siger `contains_synthetic_data: true`. Udtræk må aldrig ligge i Git.

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

Analyser og ML kører som foruddefinerede funktioner – modellen kan ikke køre vilkårlig Python, og højst
`ML_MAX_CALLS_PER_QUESTION` ML-kørsler er tilladt pr. spørgsmål. Databricks-identiteten bør være en service
principal med OAuth-secret; secrets læses kun fra miljøvariabler.

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
