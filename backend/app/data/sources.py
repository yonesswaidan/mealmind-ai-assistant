"""Read-only datakilder: lokal DuckDB (demodata), lokalt MealMind-udtræk og Azure Databricks SQL Warehouse."""

import hashlib
import json
import re
import threading
from decimal import Decimal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import duckdb
import pandas as pd

from app.config import Settings
from app.data.databricks_auth import auth_mode, sql_connect_kwargs
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
    label: str

    def tables(self) -> list[TableInfo]: ...
    def run(self, query: ValidatedQuery) -> pd.DataFrame: ...


CATEGORICAL_TYPES = ("VARCHAR", "STRING", "BOOLEAN")
# Tabelkommentarer med disse præfikser markerer syntetiske data (sættes af demo-generatoren og Databricks-pipelinen).
SYNTHETIC_PREFIXES = ("DEMODATA", "SYNTETISKE TESTDATA")
_IDENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
# Rettigheder der er i orden for MealMind Insights' identitet; alt andet (MODIFY, CREATE ..., ALL PRIVILEGES, ejerskab) afvises.
READ_PRIVILEGES = {"SELECT", "USE CATALOG", "USE SCHEMA", "BROWSE", "EXECUTE", "READ VOLUME"}

# Kendte Databricks-fejl oversat til danske forklaringer med løsning. Den oprindelige fejlkode beholdes.
_DATABRICKS_ERRORS = [
    (("INSUFFICIENT_PERMISSIONS", "PERMISSION_DENIED", "does not have", "User does not have"),
     "Databricks-identiteten mangler rettigheder. Kør databricks/sql/10_grant_aida_readonly.sql (USE CATALOG, "
     "USE SCHEMA, SELECT) og giv 'Can use' på SQL Warehouse'et."),
    (("TABLE_OR_VIEW_NOT_FOUND", "SCHEMA_NOT_FOUND", "CATALOG_NOT_FOUND", "NO_SUCH_CATALOG", "cannot be found"),
     "Tabellen, skemaet eller kataloget findes ikke eller er ikke synligt for identiteten. Er pipelinen kørt, "
     "og er DATABRICKS_TABLES korrekt?"),
    (("401", "Unauthorized", "invalid_client", "Invalid access token", "invalid_grant", "403 Client Error"),
     "Godkendelse mod Databricks fejlede. Tjek DATABRICKS_CLIENT_ID/DATABRICKS_CLIENT_SECRET (eller om "
     "DATABRICKS_TOKEN er udløbet)."),
    (("Name or service not known", "nodename nor servname", "Failed to resolve", "getaddrinfo",
      "Max retries exceeded", "Connection refused"),
     "Databricks kan ikke nås. Tjek DATABRICKS_SERVER_HOSTNAME og netværksadgang."),
    (("RESOURCE_DOES_NOT_EXIST", "404 Client Error", "warehouse", "Warehouse"),
     "SQL Warehouse'et blev ikke fundet eller er stoppet uden adgang til at starte. Tjek DATABRICKS_HTTP_PATH."),
    (("STATEMENT_TIMEOUT", "timed out", "TIMEOUT"),
     "Forespørgslen overskred tidsgrænsen. Aggregér mere i SQL eller forøg SQL_TIMEOUT_SECONDS."),
]


def friendly_databricks_error(error: Exception) -> str:
    first = (str(error).strip().splitlines() or [type(error).__name__])[0][:300]
    for needles, explanation in _DATABRICKS_ERRORS:
        if any(n in str(error) for n in needles):
            return f"{explanation} (Databricks: {first})"
    return first


def _skip_samples(column: str) -> bool:
    # Id'er og pseudonyme nøgler giver ingen mening for AI'en og skal ikke sendes til AI-tjenesten.
    name = column.lower()
    return name.endswith(("_id", "_key", "_json")) or name in ("id", "key")


class DuckDBSource:
    kind = "demo"
    dialect = "duckdb"
    is_demo = True
    label = "DEMODATA (syntetiske)"

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
                        "SELECT column_name, data_type, comment FROM duckdb_columns() "
                        "WHERE schema_name = 'main' AND table_name = ? ORDER BY column_index", [name]
                    ).fetchall()
                    count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    columns = []
                    for col, typ, col_comment in cols:
                        samples: list[str] = []
                        if typ.upper().startswith(CATEGORICAL_TYPES) and not _skip_samples(col):
                            samples = [str(r[0]) for r in con.execute(
                                f'SELECT "{col}", COUNT(*) c FROM "{name}" GROUP BY 1 ORDER BY c DESC LIMIT 12'
                            ).fetchall()]
                        columns.append(ColumnInfo(col, typ, col_comment or "", sample_values=samples))
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
    label = "Azure Databricks"

    def __init__(self, settings: Settings):
        if not (settings.databricks_server_hostname and settings.databricks_http_path):
            raise ValueError("DATABRICKS_SERVER_HOSTNAME og DATABRICKS_HTTP_PATH skal være sat.")
        auth_mode(settings)  # fejler med en forklaring, hvis hverken service principal eller token er sat
        if not settings.databricks_table_list:
            raise ValueError("DATABRICKS_TABLES skal angive mindst én tabel (catalog.schema.table eller catalog.schema.*).")
        for entry in settings.databricks_table_list:
            parts = entry.split(".")
            if len(parts) != 3 or not all(_IDENT.match(p) for p in parts[:2]) or not (
                    parts[2] == "*" or _IDENT.match(parts[2])):
                raise ValueError(f"Ugyldigt tabelnavn i DATABRICKS_TABLES: '{entry}' (forventede catalog.schema.table).")
        self.settings = settings
        self._tables: list[TableInfo] | None = None

    @property
    def is_demo(self) -> bool:
        # Rigtige data, medmindre tabellerne selv er markeret som syntetiske (fx et testkatalog).
        return any(t.description.upper().startswith(SYNTHETIC_PREFIXES) for t in self.tables())

    def _connect(self):
        from databricks import sql

        return sql.connect(
            server_hostname=self.settings.databricks_server_hostname,
            http_path=self.settings.databricks_http_path,
            session_configuration={"STATEMENT_TIMEOUT": str(int(self.settings.sql_timeout_seconds))},
            **sql_connect_kwargs(self.settings),
        )

    def _expand(self, cur) -> list[str]:
        """Udvider 'catalog.schema.*' til konkrete tabeller; tabeller der starter med '_' er interne."""
        out: list[str] = []
        for entry in self.settings.databricks_table_list:
            catalog, schema, table = entry.split(".")
            if table != "*":
                out.append(entry)
                continue
            cur.execute(f"SELECT table_name FROM `{catalog}`.information_schema.tables "
                        "WHERE table_schema = :s ORDER BY table_name", {"s": schema})
            out += [f"{catalog}.{schema}.{r[0]}" for r in cur.fetchall()
                    if not r[0].startswith("_") and _IDENT.match(r[0])]
        return list(dict.fromkeys(out))

    def tables(self) -> list[TableInfo]:
        if self._tables is None:
            try:
                self._tables = self._load_tables()
            except QueryError:
                raise
            except Exception as e:  # connectoren/SDK'et kaster mange forskellige fejltyper
                raise QueryError(friendly_databricks_error(e)) from e
        return self._tables

    def _load_tables(self) -> list[TableInfo]:
        infos, missing = [], []
        with self._connect() as con, con.cursor() as cur:
            for fq in self._expand(cur):
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
                if row is None or not cols:
                    # information_schema viser kun objekter, identiteten har adgang til.
                    missing.append(fq)
                    continue
                for col in cols:
                    if col.type.upper().startswith(CATEGORICAL_TYPES) and not _skip_samples(col.name):
                        cur.execute(
                            f"SELECT `{col.name}`, COUNT(*) c FROM `{catalog}`.`{schema}`.`{table}` "
                            "GROUP BY 1 ORDER BY c DESC LIMIT 12"
                        )
                        col.sample_values = [str(r[0]) for r in cur.fetchall()]
                cur.execute(f"SELECT COUNT(*) FROM `{catalog}`.`{schema}`.`{table}`")
                count = cur.fetchone()[0]
                infos.append(TableInfo(fq, (row[0] or "") if row else "", cols, count))
        if missing:
            raise QueryError(
                f"Tabellerne {', '.join(missing)} findes ikke eller er ikke synlige for Databricks-identiteten. "
                "Kør pipelinen (01-03) og databricks/sql/10_grant_aida_readonly.sql, eller ret DATABRICKS_TABLES.")
        if not infos:
            raise QueryError("Ingen tabeller fundet ud fra DATABRICKS_TABLES. Er pipelinen kørt, og har "
                             "identiteten USE SCHEMA/SELECT-rettigheder?")
        return infos

    def privilege_report(self) -> dict:
        """Best effort-kontrol af at identiteten kun kan læse. Rettigheder via grupper er ikke synlige her,
        så 'ok' betyder 'ingen skriverettigheder fundet' - SQL-guarden er stadig første forsvarslinje."""
        catalogs = sorted({t.split(".")[0] for t in self.settings.databricks_table_list})
        found: set[str] = set()
        owned: list[str] = []
        try:
            with self._connect() as con, con.cursor() as cur:
                for c in catalogs:
                    for view in ("catalog_privileges", "schema_privileges", "table_privileges"):
                        cur.execute(f"SELECT DISTINCT privilege_type FROM `{c}`.information_schema.{view} "
                                    "WHERE grantee = current_user()")
                        found |= {str(r[0]).upper().replace("_", " ") for r in cur.fetchall()}
                    cur.execute(f"SELECT table_schema, table_name FROM `{c}`.information_schema.tables "
                                "WHERE table_owner = current_user()")
                    owned += [f"{c}.{r[0]}.{r[1]}" for r in cur.fetchall()]
        except Exception as e:
            return {"status": "unknown", "message": f"Rettigheder kunne ikke kontrolleres: "
                                                    f"{friendly_databricks_error(e)}"}
        extra = sorted(found - READ_PRIVILEGES)
        if extra or owned:
            details = ", ".join(extra + [f"ejer af {t}" for t in owned[:5]])
            return {"status": "write_access", "message": "Databricks-identiteten har mere end læseadgang "
                    f"({details}). Brug service principalen med kun SELECT (10_grant_aida_readonly.sql)."}
        return {"status": "ok", "message": "Ingen skriverettigheder fundet for identiteten."}

    def run(self, query: ValidatedQuery) -> pd.DataFrame:
        try:
            with self._connect() as con, con.cursor() as cur:
                cur.execute(query.sql)
                rows = cur.fetchmany(self.settings.sql_row_limit)
                columns = [d[0] for d in cur.description]
        except Exception as e:  # connectoren kaster flere uafhængige fejltyper
            raise QueryError(friendly_databricks_error(e)) from e
        df = pd.DataFrame.from_records(rows, columns=columns)
        for c in df.columns:  # DECIMAL-kolonner kommer som Decimal-objekter; analyser forventer tal
            if df[c].map(lambda v: isinstance(v, Decimal)).any():
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df


_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def resolve_export_batch(path: Path) -> Path:
    """En udtræksmappe eller en mappe med flere udtræk (det nyeste batch_id vælges)."""
    path = Path(path)
    if (path / "manifest.json").is_file():
        return path
    batches = sorted(p for p in path.iterdir() if p.is_dir() and (p / "manifest.json").is_file()) \
        if path.is_dir() else []
    if not batches:
        raise ValueError(f"Intet MealMind-udtræk (manifest.json) fundet i {path}.")
    return batches[-1]


def load_export_manifest(batch: Path) -> dict:
    manifest = json.loads((batch / "manifest.json").read_text())
    if not manifest.get("quality_ok"):
        raise ValueError("Udtrækket er markeret med fejl i datakvaliteten og bruges ikke.")
    for name, info in manifest.get("datasets", {}).items():
        if not _TABLE_NAME.match(name):
            raise ValueError(f"Ugyldigt datasætnavn i manifestet: {name}")
        file = batch / info["file"]
        if file.parent.resolve() != batch.resolve() or not file.is_file():
            raise ValueError(f"Filen {info['file']} mangler i udtrækket.")
        if _sha256(file) != info.get("sha256"):
            raise ValueError(f"Checksum for {info['file']} passer ikke med manifestet - filen er ændret.")
    return manifest


class LocalExportSource(DuckDBSource):
    """Et godkendt, pseudonymiseret MealMind-udtræk (fra biteowl/data-platform) indlæst i en read-only DuckDB.

    Bruges til at analysere rigtige data, før Azure Databricks er sat op, eller offline.
    """

    kind = "local_export"

    def __init__(self, export_dir: Path, cache_dir: Path, timeout_seconds: float):
        batch = resolve_export_batch(export_dir)
        self.manifest = load_export_manifest(batch)
        self.is_demo = bool(self.manifest.get("contains_synthetic_data"))
        self.label = "Syntetisk testudtræk" if self.is_demo else f"Lokalt MealMind-udtræk {self.manifest['batch_id']}"
        digest = hashlib.sha256(json.dumps(self.manifest, sort_keys=True).encode()).hexdigest()[:12]
        db_path = Path(cache_dir) / f"export_{self.manifest['batch_id']}_{digest}.duckdb"
        if not db_path.exists():
            self._build(batch, db_path)
        super().__init__(db_path, timeout_seconds)

    def _build(self, batch: Path, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = db_path.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        prefix = ("SYNTETISKE TESTDATA - ikke rigtige brugere. " if self.is_demo else
                  f"MealMind-udtræk {self.manifest['batch_id']} (pseudonymiseret, kun læseadgang). ")
        con = duckdb.connect(str(tmp))
        try:
            for name, info in self.manifest["datasets"].items():
                path = str((batch / info["file"]).resolve())
                con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM read_parquet({_sql_literal(path)})')
                con.execute(f'COMMENT ON TABLE "{name}" IS {_sql_literal(prefix + info.get("description", ""))}')
                existing = {r[0] for r in con.execute(f'DESCRIBE "{name}"').fetchall()}
                for col in info.get("columns", []):
                    if col["name"] in existing and col.get("description"):
                        con.execute(f'COMMENT ON COLUMN "{name}"."{col["name"]}" IS '
                                    f'{_sql_literal(col["description"])}')
        finally:
            con.close()
        tmp.replace(db_path)


def create_source(settings: Settings) -> DataSource:
    if settings.data_source == "databricks":
        return DatabricksSource(settings)
    if settings.data_source == "local_export":
        if not settings.local_export_dir:
            raise ValueError("LOCAL_EXPORT_DIR skal pege på et MealMind-udtræk, når DATA_SOURCE=local_export.")
        return LocalExportSource(settings.local_export_dir, settings.demo_db_path.parent / "export_cache",
                                 settings.sql_timeout_seconds)
    from app.data.demo_data import ensure_demo_db

    ensure_demo_db(settings.demo_db_path)
    return DuckDBSource(settings.demo_db_path, settings.sql_timeout_seconds)
