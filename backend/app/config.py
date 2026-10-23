from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR.parent / ".env", extra="ignore")

    # "demo" bruger lokal DuckDB med genererede demodata; "databricks" bruger et SQL Warehouse.
    data_source: Literal["demo", "databricks"] = "demo"
    demo_db_path: Path = BACKEND_DIR / "data" / "demo.duckdb"

    databricks_server_hostname: str = ""
    databricks_http_path: str = ""
    databricks_token: str = ""
    # Kommasepareret liste af fuldt kvalificerede tabeller, fx "main.mealmind.meal_events,main.mealmind.pantry_items".
    databricks_tables: str = ""
    # JSON-objekt: {"navn": {"endpoint": "...", "description": "..."}} for Databricks Model Serving-endpoints.
    databricks_ml_endpoints: str = ""

    # Hvilken AI-tjeneste agenten bruger. Nøglerne læses kun af backend og sendes aldrig til frontend.
    ai_provider: Literal["openai", "anthropic"] = "openai"

    openai_api_key: str = ""
    openai_model: str = "gpt-6.1-sol"
    openai_reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] = "medium"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    agent_max_steps: int = 12

    sql_row_limit: int = 50_000
    sql_timeout_seconds: float = 20.0
    preview_rows: int = 25

    # Sættes ved hosting: kræver "Authorization: Bearer <token>" på alle /api-kald undtagen /api/health.
    app_access_token: str = ""
    cors_origins: str = "http://localhost:5173"
    rate_limit_per_minute: int = 20

    # Kun til automatiske tests: erstatter AI-modellen med et scriptet forløb, der stadig kører de rigtige tools.
    assistant_test_mode: bool = False

    frontend_dist: Path = Field(default=BACKEND_DIR.parent / "frontend" / "dist")

    @property
    def databricks_table_list(self) -> list[str]:
        return [t.strip() for t in self.databricks_tables.split(",") if t.strip()]

    @property
    def llm_model(self) -> str:
        return self.openai_model if self.ai_provider == "openai" else self.anthropic_model

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
