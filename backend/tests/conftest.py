import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data.demo_data import generate
from app.data.sources import DuckDBSource
from app.main import create_app
from app.tools.ml import build_registry
from app.tools.registry import ToolExecutor


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("data") / "demo.duckdb"
    generate(path)
    return path


@pytest.fixture
def settings(demo_db, tmp_path) -> Settings:
    return Settings(_env_file=None, demo_db_path=demo_db, frontend_dist=tmp_path / "no-dist",
                    assistant_test_mode=True, rate_limit_per_minute=1000)


@pytest.fixture
def source(demo_db) -> DuckDBSource:
    return DuckDBSource(demo_db, timeout_seconds=10)


@pytest.fixture
def executor(settings, source) -> ToolExecutor:
    return ToolExecutor(settings, source, build_registry(settings))


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def sse_events(response) -> list[dict]:
    return [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
