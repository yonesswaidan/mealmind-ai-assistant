"""Tool-definitioner til AI-modellen og eksekvering af tool-kald."""

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.config import Settings
from app.data.sources import DataSource, QueryError
from app.security.sql_guard import UnsafeQueryError, validate_sql
from app.tools.analysis import ANALYZE_SCHEMA, AnalyzeInput, run_analysis
from app.tools.ml import MLFunction, run_ml
from app.tools.presentation import CHART_SCHEMA, TABLE_SCHEMA, ChartInput, TableInput, build_chart, build_table
from app.tools.results import ResultStore, ToolError, describe_result, json_value


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False
    events: list[dict] = field(default_factory=list)
    summary: str = ""


def tool_definitions(ml_registry: dict[str, MLFunction]) -> list[dict]:
    ml_desc = "\n".join(f"- {f.name}: {f.description}" for f in ml_registry.values())
    return [
        {
            "name": "run_sql",
            "description": (
                "Kør én read-only SQL-forespørgsel (SELECT/WITH) mod de tilgængelige tabeller. "
                "Returnerer result_id, kolonner, antal rækker og en forhåndsvisning. Aggregér i SQL når det er muligt, "
                "så resultaterne er små. Resultatet kan bruges af analyze_data, run_ml, create_chart og show_table."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Én SELECT-sætning i databasens dialekt."},
                    "title": {"type": "string", "description": "Kort dansk titel, der beskriver resultatet."},
                },
                "required": ["sql", "title"],
            },
        },
        {
            "name": "analyze_data",
            "description": "Statistisk analyse af et tidligere resultat med pandas (ingen vilkårlig kode).",
            "input_schema": ANALYZE_SCHEMA,
        },
        {
            "name": "run_ml",
            "description": "Kør en af de tilgængelige ML-funktioner på et tidligere resultat:\n" + ml_desc,
            "input_schema": {
                "type": "object",
                "properties": {
                    "function": {"type": "string", "enum": list(ml_registry)},
                    "params": {"type": "object", "description": "Parametre til funktionen som beskrevet ovenfor."},
                },
                "required": ["function", "params"],
            },
        },
        {
            "name": "create_chart",
            "description": "Vis en graf for brugeren baseret på et resultat. Vælg den graftype der bedst viser pointen.",
            "input_schema": CHART_SCHEMA,
        },
        {
            "name": "show_table",
            "description": "Vis et resultat som tabel for brugeren (brug til oversigter, top-lister og modeloutput).",
            "input_schema": TABLE_SCHEMA,
        },
    ]


class ToolExecutor:
    def __init__(self, settings: Settings, source: DataSource, ml_registry: dict[str, MLFunction]):
        self.settings = settings
        self.source = source
        self.ml_registry = ml_registry
        self.store = ResultStore()
        self.ml_calls = 0

    def execute(self, name: str, args: dict) -> ToolOutcome:
        if not isinstance(args, dict):
            return ToolOutcome("Ugyldigt input: forventede et JSON-objekt.", is_error=True)
        try:
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return ToolOutcome(f"Ukendt tool '{name}'.", is_error=True)
            return handler(args)
        except ValidationError as e:
            return ToolOutcome(f"Ugyldigt input: {e.errors(include_url=False)}", is_error=True,
                               summary="Ugyldigt input")
        except UnsafeQueryError as e:
            return ToolOutcome(f"Forespørgslen blev afvist af sikkerhedskontrollen: {e}", is_error=True,
                               summary=f"Afvist: {e}")
        except (ToolError, QueryError) as e:
            return ToolOutcome(f"Fejl: {e}", is_error=True, summary=str(e))

    def _payload(self, data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, default=json_value)

    def _tool_run_sql(self, args: dict) -> ToolOutcome:
        sql, title = args.get("sql"), args.get("title") or "SQL-resultat"
        if not isinstance(sql, str):
            raise ToolError("Parameteren 'sql' mangler.")
        tables = [t.name for t in self.source.tables()]
        validated = validate_sql(sql, allowed_tables=tables, dialect=self.source.dialect,
                                 row_limit=self.settings.sql_row_limit)
        df = self.source.run(validated)
        result = self.store.add(df, title, origin="sql", sql=validated.sql)
        info = describe_result(result, self.settings.preview_rows)
        info["executed_sql"] = validated.sql
        if len(df) >= self.settings.sql_row_limit:
            info["warning"] = f"Resultatet er afkortet til {self.settings.sql_row_limit} rækker. Aggregér i SQL."
        return ToolOutcome(self._payload(info), summary=f"{len(df)} rækker", events=[{
            "type": "sql", "sql": validated.sql, "result_id": result.id, "row_count": len(df),
        }])

    def _tool_analyze_data(self, args: dict) -> ToolOutcome:
        params = AnalyzeInput.model_validate(args)
        result, summary = run_analysis(self.store, params)
        info = describe_result(result, self.settings.preview_rows) | {"summary": summary}
        return ToolOutcome(self._payload(info), summary=f"{params.operation}: {len(result.df)} rækker")

    def _tool_run_ml(self, args: dict) -> ToolOutcome:
        function, params = args.get("function"), args.get("params")
        if not isinstance(function, str) or not isinstance(params, dict):
            raise ToolError("run_ml kræver 'function' (tekst) og 'params' (objekt).")
        if self.ml_calls >= self.settings.ml_max_calls_per_question:
            raise ToolError(f"Grænsen på {self.settings.ml_max_calls_per_question} ML-kørsler pr. spørgsmål er nået. "
                            "Brug de resultater, der allerede er beregnet.")
        self.ml_calls += 1
        results, summary = run_ml(self.ml_registry, self.store, function, params)
        # Modeller trænet her er ad hoc-analyser. På syntetiske data må de aldrig fremstå som produktionsklare.
        summary = {**summary, "data_origin": "syntetiske testdata" if self.source.is_demo else "rigtige data",
                   "production_ready": False}
        if self.source.is_demo:
            summary["data_warning"] = "Trænet på syntetiske demodata - kun til afprøvning, ikke produktionsklar."
        info = {"function": function, "summary": summary,
                "results": [describe_result(r, min(self.settings.preview_rows, 15)) for r in results]}
        return ToolOutcome(self._payload(info), summary=f"{function} færdig", events=[{
            "type": "ml", "function": function, "summary": summary,
        }])

    def _tool_create_chart(self, args: dict) -> ToolOutcome:
        chart = build_chart(self.store, ChartInput.model_validate(args))
        return ToolOutcome(self._payload({"ok": True, "points": len(chart["data"]), "notes": chart["notes"]}),
                           summary=f"Graf: {chart['title']}", events=[{"type": "chart", "chart": chart}])

    def _tool_show_table(self, args: dict) -> ToolOutcome:
        table = build_table(self.store, TableInput.model_validate(args))
        return ToolOutcome(self._payload({"ok": True, "rows_shown": len(table["rows"]),
                                          "total_rows": table["total_rows"]}),
                           summary=f"Tabel: {table['title']}", events=[{"type": "table", "table": table}])
