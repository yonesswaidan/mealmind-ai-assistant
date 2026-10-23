"""Read-only datakilder: lokal DuckDB (demodata) og Azure Databricks SQL Warehouse."""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import duckdb
import pandas as pd

from app.config import Settings
from app.security.sql_guard import ValidatedQuery


class QueryError(RuntimeError):
    pass


@dataclass
class ColumnInfo:
    name: str
    type: str
    description: str = ""
    sample_values: list[str] = field(default_factory=list)


@dataclass
class TableInfo:
    name: str
    description: str
    columns: list[ColumnInfo]
    row_count: int | None = None

    @property
    def short_name(self) -> str:
        return self.name.split(".")[-1]


class DataSource(Protocol):
    kind: str
    dialect: str
    is_demo: bool

    def tables(self) -> list[TableInfo]: ...
    def run(self, query: ValidatedQuery) -> pd.DataFrame: ...


CATEGORICAL_TYPES = ("VARCHAR", "STRING", "BOOLEAN")


class DuckDBSource:
    kind = "demo"
    dialect = "duckdb"
    is_demo = True

    def __init__(self, path: Path, timeout_seconds: float):
        self.path = path
        self.timeout = timeout_seconds
        self._tables: list[TableInfo] | None = None

    def _connect(self) -> duckdb.DuckDBPyConnection:
        # read_only + ingen ekstern adgang: forespørgsler kan hverken skrive eller læse filer/URL'er.
        return duckdb.connect(
            str(self.path),
            read_only=True,
            config={"enable_external_access": False, "lock_configuration": True},
        )

    def tables(self) -> list[TableInfo]:
        if self._tables is None:
            con = self._connect()
            try:
                infos = []
                rows = con.execute(
                    "SELECT table_name, comment FROM duckdb_tables() WHERE schema_name = 'main' ORDER BY table_name"
                ).fetchall()
                for name, comment in rows:
                    cols = con.execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name = ? ORDER BY ordinal_position", [name]
                    ).fetchall()
                    count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    columns = []
                    for col, typ in cols:
                        samples: list[str] = []
                        if typ.upper().startswith(CATEGORICAL_TYPES):
                            samples = [str(r[0]) for r in con.execute(
                                f'SELECT "{col}", COUNT(*) c FROM "{name}" GROUP BY 1 ORDER BY c DESC LIMIT 12'
                            ).fetchall()]
                        columns.append(ColumnInfo(col, typ, sample_values=samples))
                    infos.append(TableInfo(name, comment or "", columns, count))
                self._tables = infos
            finally:
                con.close()
        return self._tables

    def run(self, query: ValidatedQuery) -> pd.DataFrame:
        con = self._connect()
        timer = threading.Timer(self.timeout, con.interrupt)
        timer.start()
        try:
            return con.execute(query.sql).df()
        except duckdb.InterruptException as e:
            raise QueryError(f"Forespørgslen overskred tidsgrænsen på {self.timeout:.0f} sekunder.") from e
        except duckdb.Error as e:
            raise QueryError(str(e).splitlines()[0]) from e
        finally:
            timer.cancel()
            con.close()


class DatabricksSource:
    kind = "databricks"
    dialect = "databricks"
    is_demo = False

    def __init__(self, settings: Settings):
        if not (settings.databricks_server_hostname and settings.databricks_http_path and settings.databricks_token):
            raise ValueError("DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH og DATABRICKS_TOKEN skal være sat.")
        if not settings.databricks_table_list:
            raise ValueError("DATABRICKS_TABLES skal angive mindst én fuldt kvalificeret tabel (catalog.schema.table).")
        self.settings = settings
        self._tables: list[TableInfo] | None = None

    def _connect(self):
        from databricks import sql

        return sql.connect(
            server_hostname=self.settings.databricks_server_hostname,
            http_path=self.settings.databricks_http_path,
            access_token=self.settings.databricks_token,
            session_configuration={"STATEMENT_TIMEOUT": str(int(self.settings.sql_timeout_seconds))},
        )

    def tables(self) -> list[TableInfo]:
        if self._tables is None:
            infos = []
            with self._connect() as con, con.cursor() as cur:
                for fq in self.settings.databricks_table_list:
                    catalog, schema, table = fq.split(".")
                    cur.execute(
                        f"SELECT comment FROM `{catalog}`.information_schema.tables "
                        "WHERE table_schema = :s AND table_name = :t", {"s": schema, "t": table}
                    )
                    row = cur.fetchone()
                    cur.execute(
                        f"SELECT column_name, full_data_type, comment FROM `{catalog}`.information_schema.columns "
                        "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position",
                        {"s": schema, "t": table},
                    )
                    cols = [ColumnInfo(r[0], r[1], r[2] or "") for r in cur.fetchall()]
                    for col in cols:
                        if col.type.upper().startswith(CATEGORICAL_TYPES):
                            cur.execute(
                                f"SELECT `{col.name}`, COUNT(*) c FROM `{catalog}`.`{schema}`.`{table}` "
                                "GROUP BY 1 ORDER BY c DESC LIMIT 12"
                            )
                            col.sample_values = [str(r[0]) for r in cur.fetchall()]
                    cur.execute(f"SELECT COUNT(*) FROM `{catalog}`.`{schema}`.`{table}`")
                    count = cur.fetchone()[0]
                    infos.append(TableInfo(fq, (row[0] if row else "") or "", cols, count))
            self._tables = infos
        return self._tables

    def run(self, query: ValidatedQuery) -> pd.DataFrame:
        try:
            with self._connect() as con, con.cursor() as cur:
                cur.execute(query.sql)
                rows = cur.fetchmany(self.settings.sql_row_limit)
                columns = [d[0] for d in cur.description]
                return pd.DataFrame.from_records(rows, columns=columns)
        except Exception as e:  # connectoren kaster flere uafhængige fejltyper
            raise QueryError(str(e).splitlines()[0]) from e


def create_source(settings: Settings) -> DataSource:
    if settings.data_source == "databricks":
        return DatabricksSource(settings)
    from app.data.demo_data import ensure_demo_db

    ensure_demo_db(settings.demo_db_path)
    return DuckDBSource(settings.demo_db_path, settings.sql_timeout_seconds)
