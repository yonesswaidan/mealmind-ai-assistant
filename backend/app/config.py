from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR.parent / ".env", extra="ignore", populate_by_name=True)

    # "demo" bruger lokal DuckDB med genererede demodata; "databricks" bruger et SQL Warehouse;
    # "local_export" bruger et godkendt, pseudonymiseret MealMind-udtræk (Parquet + manifest.json) lokalt.
    data_source: Literal["demo", "databricks", "local_export"] = "demo"
    demo_db_path: Path = BACKEND_DIR / "data" / "demo.duckdb"
    # Mappe med ét udtræk (<batch_id>/) eller en mappe med flere udtræk (det nyeste bruges).
    local_export_dir: Path | None = None

    databricks_server_hostname: str = ""
    databricks_http_path: str = ""
    databricks_token: str = ""
    # OAuth M2M med service principal (anbefalet frem for token). Bruges når begge er sat.
    databricks_client_id: str = ""
    databricks_client_secret: str = ""
    # Kommasepareret liste af tabeller (catalog.schema.table). "catalog.schema.*" tager alle tabeller i skemaet,
    # fx "mealmind.silver.*,mealmind.gold.*". Tabeller hvis navn starter med "_" udelades.
    databricks_tables: str = ""
    # Afvis opstart, hvis Databricks-identiteten har mere end læseadgang (MODIFY, CREATE ..., ejerskab).
    databricks_enforce_read_only: bool = True
    # Kun til udvikling: kan datakilden ikke åbnes, køres der videre på DEMODATA med en tydelig advarsel.
    allow_demo_fallback: bool = False
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
    # Højst så mange ML-kørsler pr. spørgsmål, så modellen ikke træner ukontrolleret.
    ml_max_calls_per_question: int = 4

    sql_row_limit: int = 50_000
    sql_timeout_seconds: float = 20.0
    preview_rows: int = 25

    # Sættes ved hosting: kræver "Authorization: Bearer <token>" på alle /api-kald undtagen /api/health.
    app_access_token: str = ""
    cors_origins: str = "http://localhost:5173"
    rate_limit_per_minute: int = 20

    # Kun til automatiske tests: erstatter AI-modellen med et scriptet forløb, der stadig kører de rigtige tools.
    # INSIGHTS_TEST_MODE er det nye navn; ASSISTANT_TEST_MODE (fra før omdøbningen) virker fortsat.
    assistant_test_mode: bool = Field(
        default=False, validation_alias=AliasChoices("insights_test_mode", "assistant_test_mode"))

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
