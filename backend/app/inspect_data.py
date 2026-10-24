"""Profilér de konfigurerede datasæt: `python -m app.inspect_data` (bruger DATA_SOURCE fra .env).

Bruges til at undersøge de rigtige datasæt - lokalt (DATA_SOURCE=local_export, fx det lokale lakehouse) eller i
Databricks, så snart adgangen er sat op.
"""

import sys

from app.config import get_settings
from app.data.sources import QueryError, create_source
from app.security.sql_guard import ValidatedQuery


def main() -> int:
    settings = get_settings()
    try:
        source = create_source(settings)
        tables = source.tables()
    except (ValueError, QueryError) as e:
        print(f"Kunne ikke forbinde: {e}", file=sys.stderr)
        return 1

    q = '"' if source.dialect == "duckdb" else "`"
    where = "Azure Databricks" if source.execution_environment == "databricks" else "lokalt (ikke Azure Databricks)"
    print(f"Datakilde: {source.kind}{' (DEMODATA)' if source.is_demo else ''} · {source.label} · beregnet {where}\n")
    for t in tables:
        print(f"== {t.name} ({t.row_count} rækker)")
        if t.description:
            print(f"   {t.description}")
        ref = t.name if source.dialect == "duckdb" else ".".join(f"`{p}`" for p in t.name.split("."))
        nulls = ", ".join(f"SUM(CASE WHEN {q}{c.name}{q} IS NULL THEN 1 ELSE 0 END)" for c in t.columns)
        distinct = ", ".join(f"COUNT(DISTINCT {q}{c.name}{q})" for c in t.columns)
        null_row = source.run(ValidatedQuery(f"SELECT {nulls} FROM {ref}", (t.name,))).iloc[0].tolist()
        dist_row = source.run(ValidatedQuery(f"SELECT {distinct} FROM {ref}", (t.name,))).iloc[0].tolist()
        for c, n, d in zip(t.columns, null_row, dist_row):
            pct = (n / t.row_count * 100) if t.row_count else 0
            samples = f"  eks: {', '.join(c.sample_values[:5])}" if c.sample_values else ""
            print(f"   - {c.name:<22} {c.type:<14} null {pct:5.1f}%  distinkte {d:<8}{samples}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
