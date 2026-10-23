from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.tools.results import ResultStore, ToolError, json_value, require_columns, to_records

MAX_CHART_POINTS = 400
MAX_CATEGORIES = 40
MAX_SERIES = 8  # antal kategoriske farver i paletten; flere serier ville genbruge farver


class ChartInput(BaseModel):
    result_id: str
    chart_type: Literal["bar", "line", "area", "scatter", "pie"]
    x: str
    y: list[str] = Field(min_length=1, max_length=6)
    title: str
    series_column: str | None = None
    stacked: bool = False
    x_label: str | None = None
    y_label: str | None = None


class TableInput(BaseModel):
    result_id: str
    title: str
    columns: list[str] | None = None
    max_rows: int = Field(default=50, ge=1, le=500)


CHART_SCHEMA = {
    "type": "object",
    "properties": {
        "result_id": {"type": "string"},
        "chart_type": {"type": "string", "enum": ["bar", "line", "area", "scatter", "pie"]},
        "x": {"type": "string", "description": "Kolonne til x-aksen (eller kategorier i pie)."},
        "y": {"type": "array", "items": {"type": "string"},
              "description": "1-6 numeriske kolonner med samme enhed (ingen dobbelt y-akse; lav hellere to grafer)."},
        "title": {"type": "string"},
        "series_column": {"type": "string",
                          "description": "Valgfri: lang-format kolonne der splitter y[0] i flere serier (fx city), "
                                         "maks. 8 serier."},
        "stacked": {"type": "boolean"},
        "x_label": {"type": "string"},
        "y_label": {"type": "string"},
    },
    "required": ["result_id", "chart_type", "x", "y", "title"],
}

TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "result_id": {"type": "string"},
        "title": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "max_rows": {"type": "integer"},
    },
    "required": ["result_id", "title"],
}


def build_chart(store: ResultStore, p: ChartInput) -> dict:
    df = store.get(p.result_id).df
    require_columns(df, p.x, *p.y, p.series_column)
    y_cols = list(p.y)
    data = df[[p.x, *y_cols] + ([p.series_column] if p.series_column else [])].copy()

    if p.series_column:
        if len(y_cols) != 1:
            raise ToolError("series_column kræver præcis én y-kolonne.")
        if data[p.series_column].nunique() > MAX_SERIES:
            raise ToolError(f"For mange serier (> {MAX_SERIES}). Filtrér eller aggreger først.")
        data = data.pivot_table(index=p.x, columns=p.series_column, values=y_cols[0], aggfunc="sum").reset_index()
        data.columns = [str(c) for c in data.columns]
        y_cols = [c for c in data.columns if c != p.x]

    for c in y_cols:
        if not pd.api.types.is_numeric_dtype(data[c]):
            converted = pd.to_numeric(data[c], errors="coerce")
            if converted.isna().all():
                raise ToolError(f"y-kolonnen '{c}' er ikke numerisk.")
            data[c] = converted

    notes = []
    if p.chart_type in ("bar", "pie") and len(data) > MAX_CATEGORIES:
        data = data.sort_values(y_cols[0], ascending=False).head(MAX_CATEGORIES)
        notes.append(f"Viser de {MAX_CATEGORIES} største kategorier.")
    if len(data) > MAX_CHART_POINTS:
        step = -(-len(data) // MAX_CHART_POINTS)
        data = data.iloc[::step]
        notes.append("Data er nedsamplet til visning.")

    return {
        "type": p.chart_type,
        "title": p.title,
        "x": p.x,
        "y": y_cols,
        "stacked": p.stacked,
        "x_label": p.x_label,
        "y_label": p.y_label,
        "data": [{c: json_value(v) for c, v in r.items()} for r in data.to_dict(orient="records")],
        "notes": notes,
    }


def build_table(store: ResultStore, p: TableInput) -> dict:
    result = store.get(p.result_id)
    df = result.df
    if p.columns:
        require_columns(df, *p.columns)
        df = df[p.columns]
    return {
        "title": p.title,
        "result_id": result.id,
        "columns": [str(c) for c in df.columns],
        "rows": to_records(df, p.max_rows),
        "total_rows": len(df),
        "sql": result.sql,
    }
