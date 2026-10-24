"""Kontrakttest: MealMind Insights på det lokale lakehouse (`python -m mealmind_data local` i biteowl/data-platform).

Fixturen er skrevet af den rigtige lokale pipeline på data-platformens håndskrevne testdatabase - SYNTETISK,
pseudonymiseret med en testnøgle og uden rigtige brugerdata (se fixtures/mealmind_lakehouse/README.md).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.prompts import build_system_prompt
from app.config import Settings
from app.data.sources import LocalExportSource
from app.main import create_app
from app.security.sql_guard import validate_sql
from tests.conftest import sse_events

FIXTURE = Path(__file__).parent / "fixtures" / "mealmind_lakehouse"


@pytest.fixture
def lakehouse(tmp_path):
    return LocalExportSource(FIXTURE, tmp_path / "cache", 10)


def lakehouse_settings(tmp_path, export_dir=FIXTURE) -> Settings:
    return Settings(_env_file=None, data_source="local_export", local_export_dir=export_dir,
                    demo_db_path=tmp_path / "data" / "demo.duckdb", frontend_dist=tmp_path / "no-dist",
                    assistant_test_mode=True, rate_limit_per_minute=1000)


def test_silver_and_gold_tables_marked_local_and_synthetic(lakehouse):
    assert lakehouse.kind == "local_lakehouse" and lakehouse.execution_environment == "local"
    assert lakehouse.is_demo  # fixturen er markeret syntetisk
    assert lakehouse.label == "Syntetiske testdata · lokalt lakehouse"
    tables = {t.name: t for t in lakehouse.tables()}
    assert {"meal_events", "shopping_food_items", "ml_model_status", "meal_similarity"} <= set(tables)
    for t in tables.values():
        assert t.description.startswith("SYNTETISKE TESTDATA")  # aldrig dobbelt eller manglende markering
        assert t.description.count("SYNTETISKE TESTDATA") == 1
        assert "ikke i Azure Databricks" in t.description
    assert "[Gold i det lokale lakehouse" in tables["meal_similarity"].description
    cols = {c.name: c for c in tables["meal_events"].columns}
    assert "is_current" in cols and "seneste fulde udtræk" in cols["is_current"].description
    status_cols = {c.name for c in tables["ml_model_status"].columns}
    assert {"model_name", "status", "reason", "production_ready", "execution_environment"} <= status_cols


def test_gold_is_queryable_and_says_where_models_were_trained(lakehouse):
    q = validate_sql("SELECT model_name, status, execution_environment, production_ready FROM ml_model_status",
                     allowed_tables=["ml_model_status"], dialect="duckdb", row_limit=50)
    df = lakehouse.run(q).set_index("model_name")
    assert set(df["execution_environment"]) == {"local"}
    assert df.at["meal_similarity", "status"] == "trained"
    assert df.at["food_waste_prediction", "status"] == "not_available"
    assert not df["production_ready"].any()  # syntetiske data er aldrig produktionsklare


def test_prompt_never_claims_databricks(lakehouse):
    prompt = build_system_prompt(lakehouse)
    assert "Intet er kørt i Azure Databricks" in prompt
    assert "modellerne trænet i det lokale lakehouse (logget i lokal MLflow)" in prompt
    assert "trænet i Azure Databricks" not in prompt
    assert "SYNTETISKE TESTDATA" in prompt  # demo-advarslen gælder stadig


def test_real_lakehouse_label_and_prompt(tmp_path):
    batch = next(p for p in FIXTURE.iterdir() if p.is_dir())
    real = tmp_path / "serving" / batch.name
    real.mkdir(parents=True)
    for f in batch.iterdir():
        (real / f.name).write_bytes(f.read_bytes())
    manifest = json.loads((real / "manifest.json").read_text()) | {"contains_synthetic_data": False}
    (real / "manifest.json").write_text(json.dumps(manifest))
    src = LocalExportSource(tmp_path / "serving", tmp_path / "cache", 10)
    assert not src.is_demo and src.label.startswith("Lokalt lakehouse · MealMind-udtræk")
    prompt = build_system_prompt(src)
    assert "MealMinds lokale lakehouse" in prompt and "Intet er kørt i Azure Databricks" in prompt


def test_api_reports_local_execution_and_runs_tools(tmp_path):
    with TestClient(create_app(lakehouse_settings(tmp_path))) as c:
        health = c.get("/api/health").json()
        assert health["data_source"] == "local_lakehouse" and health["execution_environment"] == "local"
        assert health["execution"]["engine"] == "delta-rs" and health["demo"] is True
        assert "lakehouse" not in health["execution"]  # ingen lokale stier ud af API'et

        ov = c.get("/api/overview").json()
        assert ov["execution_environment"] == "local"
        ml = {m["name"]: m for m in ov["ml_status"]}
        assert {m["source"] for m in ml.values()} == {"local_lakehouse"}  # aldrig "databricks"
        assert ml["meal_similarity"]["label"] == "Demo"
        assert ml["user_segments"]["label"] == "For lidt data"

        events = sse_events(c.post("/api/chat", json={"message": "Hvilke retter ligner hinanden mest?"}))
        assert events[-1]["type"] == "done" and all(e["ok"] for e in events if e["type"] == "step_done")
