"""Validering af AI-genereret SQL før den rammer databasen.

Forsvarslag (alle skal holde):
1. Kun én sætning, og den skal være en ren forespørgsel (SELECT/WITH/UNION).
2. Ingen DDL/DML/kommandoer nogen steder i træet.
3. Kun tabeller fra allowlisten (CTE-navne undtaget) - ingen filstier eller tabel-funktioner.
4. Farlige funktioner (fil-/netværksadgang, refleksion, hemmeligheder) afvises.
5. LIMIT håndhæves altid.
Derudover åbnes databasen read-only, og Databricks-brugeren skal kun have SELECT-rettigheder.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class UnsafeQueryError(ValueError):
    pass


def _types(*names: str) -> tuple[type, ...]:
    return tuple(t for n in names if isinstance(t := getattr(exp, n, None), type))


FORBIDDEN_NODES = _types(
    "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterTable", "TruncateTable",
    "Command", "Set", "Pragma", "Use", "Grant", "Revoke", "Copy", "Attach", "Detach", "Install",
    "LoadData", "Transaction", "Commit", "Rollback", "Describe", "Analyze", "Cache", "Uncache", "Refresh",
    "Into", "Export",
)

# Normaliserede funktionsnavne (små bogstaver). Prefixes dækker fx read_csv, read_parquet, read_text.
# ai_* (Databricks AI Functions) sender data til eksterne modeller og koster penge; vector_search ligeså.
FORBIDDEN_FUNCTION_PREFIXES = ("read_", "parquet_", "glob", "sniff_", "http_", "java_", "duckdb_", "ai_",
                               "vector_search", "try_reflect")
FORBIDDEN_FUNCTIONS = {
    "getenv", "current_setting", "query", "query_table", "reflect", "java_method", "secret",
    "system", "shell", "load_extension", "pg_read_file", "input_file_name", "ai_query", "url_decode_file",
    "which_secret", "remote", "read_files", "from_json_file",
}


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    tables: tuple[str, ...]


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() if hasattr(node, "sql_name") else type(node).__name__).lower()


def _table_ref(t: exp.Table) -> list[str]:
    return [p.lower() for p in (t.catalog, t.db, t.name) if p]


def validate_sql(sql: str, *, allowed_tables: list[str], dialect: str, row_limit: int) -> ValidatedQuery:
    """Returnerer sikker SQL med fuldt kvalificerede tabelnavne og håndhævet LIMIT, eller kaster UnsafeQueryError."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("Tom forespørgsel.")
    if len(sql) > 20_000:
        raise UnsafeQueryError("Forespørgslen er for lang.")

    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError as e:
        raise UnsafeQueryError(f"SQL kunne ikke parses: {str(e).splitlines()[0]}") from e

    if len(statements) != 1:
        raise UnsafeQueryError("Kun én SQL-sætning er tilladt pr. kald.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeQueryError("Kun læse-forespørgsler (SELECT/WITH) er tilladt.")

    for node in tree.walk():
        if FORBIDDEN_NODES and isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(f"Ikke tilladt operation: {type(node).__name__}.")
        if isinstance(node, exp.Func):
            name = _func_name(node)
            if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
                raise UnsafeQueryError(f"Funktionen '{name}' er ikke tilladt.")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    allowed = {t.lower(): t for t in allowed_tables}
    short = {}
    for fq in allowed_tables:
        short.setdefault(fq.split(".")[-1].lower(), []).append(fq)

    used: set[str] = set()
    for table in list(tree.find_all(exp.Table)):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeQueryError("Tabel-funktioner og filstier er ikke tilladt i FROM.")
        parts = _table_ref(table)
        ref = ".".join(parts)
        if len(parts) == 1 and parts[0] in cte_names:
            continue
        if ref in allowed:
            used.add(allowed[ref])
            continue
        if len(parts) == 1 and len(short.get(parts[0], [])) == 1:
            fq = short[parts[0]][0]
            new = exp.to_table(fq, dialect=dialect)
            new.set("alias", table.args.get("alias"))
            table.replace(new)
            used.add(fq)
            continue
        raise UnsafeQueryError(
            f"Tabellen '{ref}' er ikke tilgængelig. Tilladte tabeller: {', '.join(allowed_tables)}."
        )
    if not used:
        raise UnsafeQueryError("Forespørgslen skal læse fra mindst én af de tilgængelige tabeller.")

    limit = tree.args.get("limit")
    current = None
    if limit is not None:
        expr = limit.expression if isinstance(limit, exp.Limit) else limit
        if isinstance(expr, exp.Literal) and expr.is_int:
            current = int(expr.this)
    if current is None or current > row_limit:
        tree = tree.limit(row_limit)

    return ValidatedQuery(sql=tree.sql(dialect=dialect), tables=tuple(sorted(used)))
