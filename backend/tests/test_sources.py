import pytest

from app.data.sources import QueryError
from app.security.sql_guard import ValidatedQuery


def test_demo_tables_are_marked_as_demo(source):
    tables = {t.name: t for t in source.tables()}
    assert set(tables) == {"meal_events", "pantry_items"}
    assert all(t.description.startswith("DEMODATA") for t in tables.values())
    assert all(t.row_count and t.row_count > 10_000 for t in tables.values())
    status = next(c for c in tables["pantry_items"].columns if c.name == "status")
    assert set(status.sample_values) == {"used", "wasted", "in_stock"}


def test_demo_data_is_deterministic(source, tmp_path):
    from app.data.demo_data import generate
    from app.data.sources import DuckDBSource

    other = tmp_path / "again.duckdb"
    generate(other)
    q = ValidatedQuery("SELECT SUM(cost_dkk) AS s, COUNT(*) AS n FROM meal_events", ("meal_events",))
    assert DuckDBSource(other, 10).run(q).equals(source.run(q))


@pytest.mark.parametrize("sql", [
    "CREATE TABLE hacked AS SELECT 1",
    "DELETE FROM meal_events",
    "DROP TABLE meal_events",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SET enable_external_access = true",
])
def test_connection_itself_is_read_only_and_sandboxed(source, sql):
    # Selv hvis SQL-guarden blev omgået, må forbindelsen hverken skrive, læse filer eller ændre konfiguration.
    with pytest.raises(QueryError):
        source.run(ValidatedQuery(sql, ("meal_events",)))


def test_query_timeout(demo_db):
    from app.data.sources import DuckDBSource

    slow = DuckDBSource(demo_db, timeout_seconds=0.2)
    q = ValidatedQuery("SELECT COUNT(*) FROM meal_events a, meal_events b, meal_events c", ("meal_events",))
    with pytest.raises(QueryError, match="tidsgrænsen"):
        slow.run(q)
