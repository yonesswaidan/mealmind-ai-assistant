"""Kontrakttest: MealMind Insights læser et udtræk skrevet af den rigtige MealMind-eksport (biteowl/data-platform)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data.sources import LocalExportSource
from app.main import create_app
from app.tools.ml import build_registry
from app.tools.registry import ToolExecutor
from tests.conftest import sse_events

FIXTURE = Path(__file__).parent / "fixtures" / "mealmind_export"


@pytest.fixture
def export_source(tmp_path):
    return LocalExportSource(FIXTURE, tmp_path / "cache", 10)


@pytest.fixture
def export_executor(export_source, settings):
    return ToolExecutor(settings, export_source, build_registry(settings))


def test_schema_matches_mealmind_contract(export_source):
    tables = {t.name: t for t in export_source.tables()}
    assert set(tables) == {"meal_events", "shopping_food_items"}
    assert export_source.is_demo  # fixturen er markeret syntetisk
    meal = {c.name: c for c in tables["meal_events"].columns}
    assert meal["event_date"].type == "DATE" and meal["snapshot_at"].type.startswith("TIMESTAMP")
    assert meal["servings"].type == "INTEGER" and meal["is_favorite"].type == "BOOLEAN"
    assert "planned/eaten/skipped" in meal["status"].description
    assert meal["user_key"].sample_values == []  # pseudonyme nøgler sendes ikke til AI'en
    assert set(meal["status"].sample_values) == {"planned", "eaten", "skipped", "logged"}
    shop = {c.name: c for c in tables["shopping_food_items"].columns}
    assert "expired" in shop["expiry_status"].sample_values


def _sql(executor, sql):
    out = executor.execute("run_sql", {"sql": sql, "title": "t"})
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_typical_questions_run_against_the_export(export_executor):
    data = _sql(export_executor, "SELECT status, COUNT(*) AS n FROM meal_events WHERE event_source = 'meal_plan' "
                                 "GROUP BY status ORDER BY n DESC")
    assert sum(r["n"] for r in data["preview"]) == 7
    data = _sql(export_executor, "SELECT date_trunc('week', event_date) AS week, AVG(calories_kcal) AS kcal "
                                 "FROM meal_events GROUP BY 1 ORDER BY 1")
    assert data["row_count"] >= 1
    data = _sql(export_executor, "SELECT expiry_status, COUNT(*) AS n FROM shopping_food_items "
                                 "WHERE record_type = 'pantry_item' GROUP BY 1")
    assert {r["expiry_status"] for r in data["preview"]} == {"expired", "expires_within_7d", "ok", "no_expiry_date"}


def test_ml_and_visuals_on_the_export(export_executor):
    _sql(export_executor, "SELECT meal_name, calories_kcal FROM meal_events")
    out = export_executor.execute("run_ml", {"function": "find_similar", "params": {
        "result_id": "r1", "item_column": "meal_name", "query": "Kylling i karry", "top_k": 3}})
    assert not out.is_error, out.content
    summary = json.loads(out.content)["summary"]
    assert summary["query_matched"] == "Kylling i karry" and summary["production_ready"] is False
    rid = _sql(export_executor, "SELECT meal_slot, COUNT(*) AS n FROM meal_events GROUP BY 1")["result_id"]
    chart = export_executor.execute("create_chart", {"result_id": rid, "chart_type": "bar", "x": "meal_slot",
                                                     "y": ["n"], "title": "Måltider pr. type"})
    table = export_executor.execute("show_table", {"result_id": rid, "title": "Måltider pr. type"})
    assert not chart.is_error, chart.content
    assert chart.events[0]["chart"]["data"] and table.events[0]["table"]["rows"]


def test_too_small_real_shaped_data_is_refused_by_ml(export_executor):
    _sql(export_executor, "SELECT user_key, COUNT(*) AS meals, AVG(calories_kcal) AS kcal FROM meal_events "
                          "GROUP BY user_key")
    out = export_executor.execute("run_ml", {"function": "segment_clusters", "params": {
        "result_id": "r1", "feature_columns": ["meals", "kcal"], "id_column": "user_key"}})
    assert out.is_error and "mindst 10" in out.content


def test_chat_with_history_on_the_export(tmp_path):
    settings = Settings(_env_file=None, data_source="local_export", local_export_dir=FIXTURE,
                        demo_db_path=tmp_path / "data" / "demo.duckdb", frontend_dist=tmp_path / "no-dist",
                        assistant_test_mode=True)
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/health").json()["data_label"] == "Syntetisk testudtræk"
        first = sse_events(c.post("/api/chat", json={"message": "Hvordan fordeler måltiderne sig over tid?"}))
        answer = "".join(e["text"] for e in first if e["type"] == "text_delta")
        follow = sse_events(c.post("/api/chat", json={
            "message": "Og hvad med de seneste uger?",
            "history": [{"role": "user", "content": "Hvordan fordeler måltiderne sig over tid?"},
                        {"role": "assistant", "content": answer}]}))
        assert follow[-1]["type"] == "done"
        assert {"sql", "chart", "table"} <= {e["type"] for e in follow}


def test_overview_on_mealmind_export(tmp_path):
    settings = Settings(_env_file=None, data_source="local_export", local_export_dir=FIXTURE,
                        demo_db_path=tmp_path / "data" / "demo.duckdb", frontend_dist=tmp_path / "no-dist",
                        assistant_test_mode=True)
    with TestClient(create_app(settings)) as c:
        ov = c.get("/api/overview").json()
    assert [s["title"] for s in ov["sources"]] == ["Måltider", "Indkøb og køkkenskab"]
    assert ov["demo"] is True  # fixturen er markeret syntetisk
    assert ov["quick_actions"][2]["label"] == "Find lignende retter"
    assert "Hvilke varer udløber snart?" in ov["next_questions"]
