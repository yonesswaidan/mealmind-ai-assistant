import pytest

from app.security.sql_guard import UnsafeQueryError, validate_sql

DUCK = dict(allowed_tables=["meal_events", "pantry_items"], dialect="duckdb", row_limit=100)
DBX = dict(allowed_tables=["main.mealmind.meal_events", "main.mealmind.pantry_items"], dialect="databricks",
           row_limit=100)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM meal_events",
    "select city, count(*) from meal_events group by city order by 2 desc",
    "WITH w AS (SELECT * FROM pantry_items WHERE status = 'wasted') SELECT category, COUNT(*) FROM w GROUP BY 1",
    "SELECT a.user_id FROM meal_events a JOIN pantry_items b ON a.user_id = b.user_id",
    "SELECT city FROM meal_events UNION ALL SELECT city FROM pantry_items",
    "SELECT * FROM (SELECT user_id FROM meal_events) sub",
    "SELECT COUNT(*) FROM meal_events WHERE meal_name LIKE '%; DROP TABLE x; --%'",
])
def test_allows_read_queries(sql):
    out = validate_sql(sql, **DUCK)
    assert "LIMIT" in out.sql.upper()


@pytest.mark.parametrize("sql", [
    "DROP TABLE meal_events",
    "DELETE FROM meal_events",
    "UPDATE meal_events SET city = 'x'",
    "INSERT INTO meal_events SELECT * FROM meal_events",
    "CREATE TABLE x AS SELECT * FROM meal_events",
    "ALTER TABLE meal_events ADD COLUMN x INT",
    "SELECT 1; DROP TABLE meal_events",
    "SELECT * FROM meal_events; SELECT * FROM pantry_items",
    "ATTACH 'other.db' AS o",
    "COPY meal_events TO 'out.csv'",
    "PRAGMA database_list",
    "SET threads = 1",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_parquet('s3://bucket/x.parquet')",
    "SELECT * FROM '/etc/passwd'",
    "SELECT * FROM 'data.csv'",
    "SELECT getenv('HOME')",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM users",
    "SELECT * FROM information_schema.tables",
    "SELECT 1",
    "",
    "SELEC * FROM meal_events",
    "SELECT * INTO new_table FROM meal_events",
])
def test_rejects_unsafe_queries(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql, **DUCK)


def test_enforces_row_limit():
    assert validate_sql("SELECT * FROM meal_events LIMIT 100000", **DUCK).sql.endswith("LIMIT 100")
    assert validate_sql("SELECT * FROM meal_events LIMIT 5", **DUCK).sql.endswith("LIMIT 5")


def test_databricks_short_names_are_qualified():
    out = validate_sql("SELECT m.city FROM meal_events m", **DBX)
    assert "main.mealmind.meal_events" in out.sql
    assert out.tables == ("main.mealmind.meal_events",)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM parquet.`/mnt/data/x`",
    "SELECT reflect('java.lang.Runtime', 'getRuntime')",
    "SELECT java_method('java.lang.System', 'getenv', 'X')",
    "SELECT secret('scope', 'key')",
    "SELECT * FROM other_catalog.mealmind.meal_events",
    "SELECT * FROM read_files('/Volumes/x')",
    "SELECT ai_query('model', 'prompt')",
    "SELECT ai_generate_text(meal_name, 'model') FROM meal_events",
    "SELECT ai_analyze_sentiment(meal_name) FROM meal_events",
    "SELECT * FROM vector_search(index => 'x', query => 'y')",
    "SELECT http_request(conn => 'x', method => 'GET', path => '/')",
    "SELECT try_reflect('java.lang.System', 'getenv')",
])
def test_databricks_rejects_unsafe(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql, **DBX)
