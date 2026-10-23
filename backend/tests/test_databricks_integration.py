"""MealMind-integrationen: Databricks (mocket), lokalt udtræk, automatisk værktøjsvalg og ML-guardrails."""

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.agent.agent import AgentDeps, ChatRequest, run_agent
from app.agent.llm import ToolUse, Turn
from app.agent.prompts import build_system_prompt
from app.agent.router import plan_question
from app.config import Settings
from app.data import databricks_auth
from app.data.databricks_auth import DatabricksConfigError, rest_headers, sql_connect_kwargs
from app.data.sources import DatabricksSource, LocalExportSource, QueryError, create_source
from app.main import create_app
from app.security.sql_guard import ValidatedQuery
from app.tools.ml import build_registry
from app.tools.registry import ToolExecutor, tool_definitions
from tests.conftest import sse_events

# ── Automatisk værktøjsvalg ──────────────────────────────────────────────


@pytest.mark.parametrize("question,caps,ml", [
    ("Hvor mange måltider blev registreret i september?", ["sql"], []),
    ("Hvad er gennemsnittet af kalorier pr. måltid?", ["sql", "statistics"], []),
    ("Lav en prognose for antal måltider de næste 4 uger", ["sql", "forecast", "visualization"],
     ["forecast_timeseries"]),
    ("Hvilke retter ligner Kylling i karry?", ["sql", "similarity"], ["find_similar"]),
    ("Kan vi gruppere brugerne i segmenter efter adfærd?", ["sql", "segmentation"], ["segment_clusters"]),
    ("Var der usædvanlige dage i kalorieindtaget?", ["sql", "anomaly", "visualization"], ["detect_anomalies"]),
    ("Hvad er risikoen for at et måltid springes over?", ["sql", "classification"], ["predict_outcome"]),
    ("Vis en graf over udviklingen og forudsig næste måned",
     ["sql", "forecast", "statistics", "visualization"], ["forecast_timeseries"]),
])
def test_router_classifies_questions(question, caps, ml):
    plan = plan_question(question)
    assert plan.capabilities == caps
    assert plan.ml_functions == ml
    assert plan.needs_ml == bool(ml)
    assert ("run_ml" in plan.tools) == bool(ml)


def test_router_flags_food_waste_and_respects_registry():
    plan = plan_question("Hvor meget madspild har brugerne?")
    assert "food_waste" in plan.capabilities and "Udløbsdatoer er ikke spild" in plan.hint()
    assert plan_question("Lav en prognose", available_ml=["segment_clusters"]).ml_functions == []
    assert not plan_question("Hvor mange brugere er der?").has_hint


def test_chat_emits_plan_and_runs_forecast_with_ml(client):
    events = sse_events(client.post("/api/chat", json={"message": "Lav en prognose for aktiviteten de næste uger"}))
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["ml_functions"] == ["forecast_timeseries"] and "Prognose" in plan["labels"]
    assert [e["tool"] for e in events if e["type"] == "step"] == ["run_sql", "run_ml", "create_chart"]
    ml = next(e for e in events if e["type"] == "ml")
    assert ml["function"] == "forecast_timeseries" and ml["summary"]["backtest_mae"] is not None
    text = "".join(e["text"] for e in events if e["type"] == "text_delta")
    assert f"{ml['summary']['next_period_forecast']:.0f}" in text  # svaret bygger på det beregnede tal
    assert not any(e["type"] == "notice" for e in events)
    assert events[-1]["type"] == "done"


# ── ML-værktøjer og guardrails ───────────────────────────────────────────


def test_find_similar_meals(executor):
    out = executor.execute("run_sql", {"sql": "SELECT meal_name, calories, protein_g FROM meal_events", "title": "m"})
    assert not out.is_error
    out = executor.execute("run_ml", {"function": "find_similar", "params": {
        "result_id": "r1", "item_column": "meal_name", "query": "kylling karry", "top_k": 3,
        "feature_columns": ["calories", "protein_g"]}})
    data = json.loads(out.content)
    assert data["summary"]["query_matched"] == "Kylling i karry"
    rows = data["results"][0]["preview"]
    assert len(rows) == 3 and rows[0]["rank"] == 1 and 0 < rows[0]["similarity"] <= 1


def test_find_similar_requires_enough_items(executor):
    executor.execute("run_sql", {"sql": "SELECT DISTINCT city FROM meal_events LIMIT 2", "title": "c"})
    out = executor.execute("run_ml", {"function": "find_similar", "params": {"result_id": "r1", "item_column": "city"}})
    assert out.is_error and "mindst 3" in out.content


def test_ml_calls_are_capped_per_question(settings, source):
    settings.ml_max_calls_per_question = 1
    ex = ToolExecutor(settings, source, build_registry(settings))
    ex.execute("run_sql", {"sql": "SELECT event_date, COUNT(*) AS n FROM meal_events GROUP BY 1", "title": "t"})
    params = {"function": "detect_anomalies", "params": {"result_id": "r1", "value_column": "n"}}
    assert not ex.execute("run_ml", params).is_error
    second = ex.execute("run_ml", params)
    assert second.is_error and "Grænsen på 1 ML-kørsler" in second.content


class NoToolLLM:
    def __init__(self, text):
        self.text = text

    async def turn(self, *, system, tools, messages, on_text):
        await on_text(self.text)
        return Turn(content=[{"type": "text", "text": self.text}], stop_reason="end_turn", tool_uses=[])


class OneSqlLLM:
    async def turn(self, *, system, tools, messages, on_text):
        if not any(isinstance(m["content"], list) for m in messages if m["role"] == "user"):
            block = {"type": "tool_use", "id": "t1", "name": "run_sql",
                     "input": {"sql": "SELECT COUNT(*) AS n FROM meal_events", "title": "n"}}
            return Turn(content=[block], stop_reason="tool_use", tool_uses=[ToolUse("t1", "run_sql", block["input"])])
        await on_text("Der er 42 rækker.")
        return Turn(content=[{"type": "text", "text": "Der er 42 rækker."}], stop_reason="end_turn", tool_uses=[])


async def _events(settings, source, llm, message="Hvor mange brugere er der?"):
    registry = build_registry(settings)
    deps = AgentDeps(settings, source, registry, llm, build_system_prompt(source), tool_definitions(registry))
    return [e async for e in run_agent(ChatRequest(message=message), deps)]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_numbers_without_data_trigger_notice(settings, source):
    events = await _events(settings, source, NoToolLLM("Der er 300 brugere."))
    notice = [e for e in events if e["type"] == "notice"]
    assert notice and "ikke hentet" in notice[0]["message"] and events[-1]["type"] == "done"
    assert not [e for e in await _events(settings, source, NoToolLLM("Hej! Spørg løs.")) if e["type"] == "notice"]
    assert not [e for e in await _events(settings, source, OneSqlLLM()) if e["type"] == "notice"]


def test_system_prompt_guides_tool_choice(source):
    prompt = build_system_prompt(source)
    assert "ml_model_status" in prompt and "is_current" in prompt and "madspild" in prompt
    assert "DEMODATA" in prompt


# ── Lokalt MealMind-udtræk (DATA_SOURCE=local_export) ────────────────────


def make_export(root: Path, batch_id="20261020T120000Z", synthetic=True) -> Path:
    """Skriver et lille udtræk i samme format som biteowl/data-platform (TESTDATA, ikke brugere)."""
    batch = root / batch_id
    batch.mkdir(parents=True)
    con = duckdb.connect()
    con.execute("""CREATE TABLE meal_events AS SELECT * FROM (VALUES
        ('e1', 'u1', DATE '2026-10-01', 'dinner', 'meal_plan', 'eaten', 'Kylling i karry', 640.0),
        ('e2', 'u1', DATE '2026-10-02', 'lunch', 'meal_plan', 'skipped', 'Linsesalat', 480.0),
        ('e3', 'u2', DATE '2026-10-02', 'dinner', 'food_log', 'logged', 'Tofu wok', 590.0))
        AS t(event_id, user_key, event_date, meal_slot, event_source, status, meal_name, calories_kcal)""")
    con.execute("""CREATE TABLE shopping_food_items AS SELECT * FROM (VALUES
        ('s1', 'u1', 'pantry_item', 'spinat', 'expired'), ('s2', 'u2', 'shopping_list_item', 'mælk', 'not_applicable'))
        AS t(record_id, user_key, record_type, item_name, expiry_status)""")
    datasets = {}
    for name, desc in (("meal_events", "Måltidshændelser"), ("shopping_food_items", "Indkøb og køkkenskab")):
        path = batch / f"{name}.parquet"
        con.execute(f"COPY {name} TO '{path}' (FORMAT parquet)")
        datasets[name] = {
            "file": path.name, "rows": con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "description": desc,
            "columns": [{"name": "status", "description": "planned/eaten/skipped/logged"}],
        }
    (batch / "manifest.json").write_text(json.dumps({
        "batch_id": batch_id, "quality_ok": True, "contains_synthetic_data": synthetic, "datasets": datasets}))
    return batch


def test_local_export_source(tmp_path):
    make_export(tmp_path / "exports", "20261001T000000Z")
    make_export(tmp_path / "exports", "20261020T120000Z")
    src = LocalExportSource(tmp_path / "exports", tmp_path / "cache", 5)
    assert src.manifest["batch_id"] == "20261020T120000Z"  # nyeste batch vælges
    tables = {t.name: t for t in src.tables()}
    assert set(tables) == {"meal_events", "shopping_food_items"}
    assert tables["meal_events"].description.startswith("SYNTETISKE TESTDATA") and src.is_demo
    status = next(c for c in tables["meal_events"].columns if c.name == "status")
    assert status.description == "planned/eaten/skipped/logged" and "eaten" in status.sample_values
    df = src.run(ValidatedQuery("SELECT COUNT(*) AS n FROM meal_events", ("meal_events",)))
    assert df.n[0] == 3
    with pytest.raises(QueryError):
        src.run(ValidatedQuery("DELETE FROM meal_events", ("meal_events",)))


def test_local_export_real_flag_changes_label_and_prompt(tmp_path):
    src = LocalExportSource(make_export(tmp_path / "e", synthetic=False), tmp_path / "cache", 5)
    assert not src.is_demo and src.label.startswith("Lokalt MealMind-udtræk")
    prompt = build_system_prompt(src)
    assert "pseudonymiseret udtræk" in prompt and "DEMODATA" not in prompt


def test_local_export_rejects_tampered_or_failed_batches(tmp_path):
    batch = make_export(tmp_path / "e")
    with (batch / "meal_events.parquet").open("ab") as f:
        f.write(b"x")
    with pytest.raises(ValueError, match="Checksum"):
        LocalExportSource(batch, tmp_path / "cache", 5)
    batch2 = make_export(tmp_path / "f")
    manifest = json.loads((batch2 / "manifest.json").read_text()) | {"quality_ok": False}
    (batch2 / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="datakvaliteten"):
        LocalExportSource(batch2, tmp_path / "cache", 5)
    with pytest.raises(ValueError, match="Intet MealMind-udtræk"):
        LocalExportSource(tmp_path / "tom", tmp_path / "cache", 5)


def test_api_with_local_export(tmp_path):
    make_export(tmp_path / "exports")
    settings = Settings(_env_file=None, data_source="local_export", local_export_dir=tmp_path / "exports",
                        demo_db_path=tmp_path / "data" / "demo.duckdb", frontend_dist=tmp_path / "no-dist",
                        assistant_test_mode=True)
    with TestClient(create_app(settings)) as c:
        health = c.get("/api/health").json()
        assert health["data_source"] == "local_export" and health["demo"] is True
        tables = c.get("/api/datasets").json()["tables"]
        assert {t["name"] for t in tables} == {"meal_events", "shopping_food_items"}
        events = sse_events(c.post("/api/chat", json={"message": "Hvordan fordeler måltiderne sig?"}))
        assert events[-1]["type"] == "done" and all(e["ok"] for e in events if e["type"] == "step_done")


def test_local_export_requires_dir(tmp_path):
    with pytest.raises(ValueError, match="LOCAL_EXPORT_DIR"):
        create_source(Settings(_env_file=None, data_source="local_export"))


# ── Azure Databricks (mocket SQL Warehouse) ──────────────────────────────

INFO = {
    "silver": {
        "meal_events": ("Måltidshændelser (pseudonymiseret)", [
            ("event_id", "string", "Nøgle"), ("user_key", "string", "Pseudonym bruger"),
            ("event_date", "date", "Dato"), ("status", "string", "planned/eaten/skipped/logged"),
            ("calories_kcal", "double", "Kalorier"), ("is_current", "boolean", "Seneste udtræk")]),
        "shopping_food_items": ("Indkøb og køkkenskab", [("record_id", "string", ""), ("item_name", "string", "")]),
        "_ingest_log": ("intern", [("batch_id", "string", "")]),
    },
    "gold": {"ml_model_status": ("Status for ML-modeller", [("model_name", "string", ""), ("status", "string", ""),
                                                            ("reason", "string", "")])},
}


class FakeCursor:
    def __init__(self, log, fail=False):
        self.log, self.fail, self.rows, self.description = log, fail, [], []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        if self.fail:
            raise RuntimeError("[INSUFFICIENT_PERMISSIONS] User does not have SELECT on table\nstacktrace")
        p = params or {}
        if "information_schema.tables" in sql and "table_name =" not in sql:
            self.rows = [(t,) for t in sorted(INFO[p["s"]])]
        elif "information_schema.tables" in sql:
            self.rows = [(INFO[p["s"]][p["t"]][0],)]
        elif "information_schema.columns" in sql:
            self.rows = list(INFO[p["s"]][p["t"]][1])
        elif "GROUP BY 1" in sql:
            self.rows = [("eaten", 5), ("skipped", 2)]
        elif "COUNT(*)" in sql and "information_schema" not in sql and "FROM `" in sql:
            self.rows = [(7,)]
        else:
            self.rows = [("eaten", 5), ("skipped", 2)]
            self.description = [("status",), ("n",)]

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchmany(self, n):
        return self.rows[:n]


class FakeConnection:
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self.log, self.fail)


@pytest.fixture
def fake_databricks(monkeypatch):
    calls = {"connect": [], "sql": [], "fail": False}

    def connect(**kwargs):
        calls["connect"].append(kwargs)
        return FakeConnection(calls["sql"], calls["fail"])

    from databricks import sql as dbsql
    monkeypatch.setattr(dbsql, "connect", connect)
    return calls


def db_settings(**kw) -> Settings:
    base = dict(_env_file=None, data_source="databricks", databricks_server_hostname="adb-1.2.azuredatabricks.net",
                databricks_http_path="/sql/1.0/warehouses/abc", databricks_token="dapi-test",
                databricks_tables="mealmind.silver.*,mealmind.gold.ml_model_status", assistant_test_mode=True)
    return Settings(**(base | kw))


def test_databricks_discovers_tables_with_comments(fake_databricks):
    src = DatabricksSource(db_settings())
    tables = {t.name: t for t in src.tables()}
    assert set(tables) == {"mealmind.silver.meal_events", "mealmind.silver.shopping_food_items",
                           "mealmind.gold.ml_model_status"}  # _ingest_log er intern og udelades
    meal = tables["mealmind.silver.meal_events"]
    assert meal.row_count == 7 and meal.description.startswith("Måltidshændelser")
    status = next(c for c in meal.columns if c.name == "status")
    assert status.description == "planned/eaten/skipped/logged" and status.sample_values == ["eaten", "skipped"]
    assert not src.is_demo and src.label == "Azure Databricks"
    kwargs = fake_databricks["connect"][0]
    assert kwargs["access_token"] == "dapi-test" and kwargs["session_configuration"]["STATEMENT_TIMEOUT"] == "20"


def test_databricks_query_through_tools_is_guarded(fake_databricks):
    settings = db_settings()
    src = DatabricksSource(settings)
    ex = ToolExecutor(settings, src, build_registry(settings))
    out = ex.execute("run_sql", {"sql": "SELECT status, COUNT(*) AS n FROM meal_events WHERE is_current "
                                        "GROUP BY status", "title": "Status"})
    assert not out.is_error, out.content
    executed = fake_databricks["sql"][-1][0]
    assert "FROM mealmind.silver.meal_events" in executed and "LIMIT" in executed
    blocked = ex.execute("run_sql", {"sql": "DELETE FROM meal_events", "title": "x"})
    assert blocked.is_error and "sikkerhedskontrollen" in blocked.content
    other = ex.execute("run_sql", {"sql": "SELECT * FROM mealmind.bronze.meal_events", "title": "x"})
    assert other.is_error and "ikke tilgængelig" in other.content


def test_databricks_errors_are_reported_without_stacktrace(fake_databricks):
    src = DatabricksSource(db_settings())
    src.tables()
    fake_databricks["fail"] = True
    with pytest.raises(QueryError) as e:
        src.run(ValidatedQuery("SELECT 1", ("x",)))
    assert "INSUFFICIENT_PERMISSIONS" in str(e.value) and "stacktrace" not in str(e.value)


def test_databricks_detects_synthetic_catalog(fake_databricks, monkeypatch):
    monkeypatch.setitem(INFO["silver"], "meal_events", ("SYNTETISKE TESTDATA - ikke rigtige brugere.",
                                                        INFO["silver"]["meal_events"][1]))
    src = DatabricksSource(db_settings())
    assert src.is_demo and "DEMODATA" in build_system_prompt(src)


class FakeSdkConfig:
    """Erstatter databricks.sdk Config, som ellers kontakter Entra ID/Databricks ved oprettelse."""

    def __init__(self, **kw):
        self.host, self.client_id, self.client_secret = kw["host"], kw["client_id"], kw["client_secret"]

    def authenticate(self):
        return {"Authorization": "Bearer from-oauth"}


def test_databricks_uses_service_principal_oauth(fake_databricks, monkeypatch):
    seen = {}
    monkeypatch.setattr("databricks.sdk.core.Config", FakeSdkConfig)
    monkeypatch.setattr("databricks.sdk.core.oauth_service_principal",
                        lambda cfg: seen.setdefault("cfg", cfg) and (lambda: {"Authorization": "Bearer oauth"}))
    settings = db_settings(databricks_token="", databricks_client_id="sp-id", databricks_client_secret="sp-secret")
    DatabricksSource(settings).tables()
    kwargs = fake_databricks["connect"][0]
    assert "access_token" not in kwargs and callable(kwargs["credentials_provider"])
    kwargs["credentials_provider"]()
    assert seen["cfg"].client_id == "sp-id" and seen["cfg"].host == "https://adb-1.2.azuredatabricks.net"


@pytest.mark.parametrize("kw,msg", [
    ({"databricks_token": ""}, "DATABRICKS_CLIENT_ID"),
    ({"databricks_http_path": ""}, "DATABRICKS_HTTP_PATH"),
    ({"databricks_tables": ""}, "DATABRICKS_TABLES"),
    ({"databricks_tables": "mealmind.silver"}, "Ugyldigt tabelnavn"),
    ({"databricks_tables": "mealmind.silver.x; DROP TABLE y"}, "Ugyldigt tabelnavn"),
])
def test_databricks_missing_or_invalid_config(kw, msg):
    with pytest.raises(ValueError, match=msg):
        DatabricksSource(db_settings(**kw))


def test_databricks_no_tables_found_is_explained(fake_databricks, monkeypatch):
    monkeypatch.setitem(INFO, "silver", {})
    with pytest.raises(QueryError, match="Ingen tabeller fundet"):
        DatabricksSource(db_settings(databricks_tables="mealmind.silver.*")).tables()


def test_app_starts_against_mocked_databricks(fake_databricks):
    with TestClient(create_app(db_settings())) as c:
        h = c.get("/api/health").json()
        assert h["data_source"] == "databricks" and h["demo"] is False and h["data_label"] == "Azure Databricks"
        tables = c.get("/api/datasets").json()["tables"]
        assert "mealmind.gold.ml_model_status" in {t["name"] for t in tables}


def test_rest_headers_for_model_serving(monkeypatch):
    assert rest_headers(db_settings()) == {"Authorization": "Bearer dapi-test"}

    monkeypatch.setattr("databricks.sdk.core.Config", FakeSdkConfig)
    oauth = db_settings(databricks_token="", databricks_client_id="id", databricks_client_secret="secret")
    assert rest_headers(oauth) == {"Authorization": "Bearer from-oauth"}
    assert "credentials_provider" in sql_connect_kwargs(oauth)
    with pytest.raises(DatabricksConfigError):
        databricks_auth.auth_mode(db_settings(databricks_token=""))


def test_model_serving_endpoint_tool(monkeypatch, executor):
    import app.tools.ml as ml

    settings = db_settings(databricks_ml_endpoints=json.dumps({"skip": {"endpoint": "mealmind-skip"}}))
    registry = build_registry(settings)
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"predictions": [0.2, 0.7]}).encode()

    def urlopen(req, timeout):
        sent["url"], sent["auth"] = req.full_url, req.headers["Authorization"]
        return Resp()

    monkeypatch.setattr(ml.urllib.request, "urlopen", urlopen)
    executor.ml_registry = registry
    executor.store.add(pd.DataFrame({"meal_slot": ["dinner", "lunch"]}), "x", origin="sql")
    out = executor.execute("run_ml", {"function": "endpoint_skip", "params": {"result_id": "r1"}})
    assert not out.is_error, out.content
    assert sent["url"].endswith("/serving-endpoints/mealmind-skip/invocations") and sent["auth"] == "Bearer dapi-test"
    assert json.loads(out.content)["results"][0]["preview"][1]["prediction"] == 0.7
