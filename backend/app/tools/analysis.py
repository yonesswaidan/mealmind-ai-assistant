"""Deterministiske pandas-analyser. Modellen vælger operation og kolonner; ingen vilkårlig kode køres."""

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.tools.results import ResultStore, StoredResult, ToolError, json_value, require_columns

Agg = Literal["sum", "mean", "median", "min", "max", "count", "nunique", "std"]
Freq = Literal["D", "W", "M", "Q"]
FREQ_ALIAS = {"D": "D", "W": "W-MON", "M": "MS", "Q": "QS"}


class Metric(BaseModel):
    column: str
    agg: Agg
    alias: str | None = None


class AnalyzeInput(BaseModel):
    result_id: str
    operation: Literal["summary_stats", "group_aggregate", "correlation", "trend", "distribution", "top_n",
                       "pivot", "share"]
    group_by: list[str] | None = None
    metrics: list[Metric] | None = None
    columns: list[str] | None = None
    date_column: str | None = None
    value_column: str | None = None
    freq: Freq | None = None
    n: int | None = Field(default=None, ge=1, le=1000)
    sort_by: str | None = None
    ascending: bool | None = None
    bins: int | None = Field(default=None, ge=2, le=60)
    pivot_index: str | None = None
    pivot_columns: str | None = None
    title: str | None = None


ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "result_id": {"type": "string", "description": "Id på et tidligere resultat, fx 'r1'."},
        "operation": {
            "type": "string",
            "enum": list(AnalyzeInput.model_fields["operation"].annotation.__args__),
            "description": (
                "summary_stats: statistik for numeriske kolonner (columns valgfri). "
                "group_aggregate: group_by + metrics. "
                "correlation: korrelationsmatrix for columns. "
                "trend: date_column + value_column (+ freq, standard M) -> periodisk sum, hældning, ændring i %. "
                "distribution: histogram af value_column (bins). "
                "top_n: n rækker sorteret efter sort_by. "
                "pivot: pivot_index x pivot_columns med metrics[0]. "
                "share: andel (%) af value_column (eller antal rækker) pr. group_by."
            ),
        },
        "group_by": {"type": "array", "items": {"type": "string"}},
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "agg": {"type": "string", "enum": ["sum", "mean", "median", "min", "max", "count", "nunique", "std"]},
                    "alias": {"type": "string"},
                },
                "required": ["column", "agg"],
            },
        },
        "columns": {"type": "array", "items": {"type": "string"}},
        "date_column": {"type": "string"},
        "value_column": {"type": "string"},
        "freq": {"type": "string", "enum": ["D", "W", "M", "Q"]},
        "n": {"type": "integer"},
        "sort_by": {"type": "string"},
        "ascending": {"type": "boolean"},
        "bins": {"type": "integer"},
        "pivot_index": {"type": "string"},
        "pivot_columns": {"type": "string"},
        "title": {"type": "string", "description": "Kort dansk titel på resultatet."},
    },
    "required": ["result_id", "operation"],
}


def _numeric(df: pd.DataFrame, cols: list[str] | None) -> pd.DataFrame:
    if cols:
        require_columns(df, *cols)
        sub = df[cols]
    else:
        sub = df
    num = sub.select_dtypes(include="number")
    if num.empty:
        raise ToolError("Ingen numeriske kolonner at analysere.")
    return num


def _aggregate(df: pd.DataFrame, group_by: list[str], metrics: list[Metric]) -> pd.DataFrame:
    require_columns(df, *group_by, *[m.column for m in metrics])
    named = {(m.alias or f"{m.agg}_{m.column}"): pd.NamedAgg(column=m.column, aggfunc=m.agg) for m in metrics}
    return df.groupby(group_by, dropna=False).agg(**named).reset_index()


def run_analysis(store: ResultStore, params: AnalyzeInput) -> tuple[StoredResult, dict]:
    src = store.get(params.result_id)
    df = src.df
    op = params.operation
    summary: dict = {"operation": op}

    if op == "summary_stats":
        num = _numeric(df, params.columns)
        out = num.describe(percentiles=[0.25, 0.5, 0.75]).T.reset_index().rename(columns={"index": "column"})
        out["missing"] = [int(df[c].isna().sum()) for c in out["column"]]

    elif op == "group_aggregate":
        if not params.group_by or not params.metrics:
            raise ToolError("group_aggregate kræver group_by og metrics.")
        out = _aggregate(df, params.group_by, params.metrics)
        if params.sort_by:
            require_columns(out, params.sort_by)
            out = out.sort_values(params.sort_by, ascending=bool(params.ascending))

    elif op == "correlation":
        num = _numeric(df, params.columns)
        if num.shape[1] < 2:
            raise ToolError("correlation kræver mindst to numeriske kolonner.")
        corr = num.corr().round(3)
        out = corr.reset_index().rename(columns={"index": "column"})
        pairs = corr.where(np.triu(np.ones(corr.shape, dtype=bool), k=1)).stack().sort_values(key=abs, ascending=False)
        summary["strongest_pairs"] = [{"a": a, "b": b, "r": json_value(r)} for (a, b), r in pairs.head(5).items()]

    elif op == "trend":
        if not params.date_column or not params.value_column:
            raise ToolError("trend kræver date_column og value_column.")
        require_columns(df, params.date_column, params.value_column)
        freq = params.freq or "M"
        s = df[[params.date_column, params.value_column]].copy()
        s[params.date_column] = pd.to_datetime(s[params.date_column])
        out = (s.set_index(params.date_column)[params.value_column]
               .resample(FREQ_ALIAS[freq]).sum(min_count=1).reset_index())
        out.columns = ["period", params.value_column]
        vals = out[params.value_column].astype(float)
        if vals.notna().sum() >= 2:
            x = np.arange(len(vals))[vals.notna()]
            y = vals.dropna().values
            slope, intercept = np.polyfit(x, y, 1)
            fitted = slope * x + intercept
            ss_res = float(((y - fitted) ** 2).sum())
            ss_tot = float(((y - y.mean()) ** 2).sum()) or 1.0
            first, last = y[0], y[-1]
            summary.update({
                "periods": int(len(y)),
                "slope_per_period": json_value(slope),
                "r_squared": json_value(1 - ss_res / ss_tot),
                "first_value": json_value(first),
                "last_value": json_value(last),
                "pct_change_first_to_last": json_value((last - first) / first * 100) if first else None,
                "note": "Første/sidste periode kan være ufuldstændig.",
            })

    elif op == "distribution":
        if not params.value_column:
            raise ToolError("distribution kræver value_column.")
        require_columns(df, params.value_column)
        vals = pd.to_numeric(df[params.value_column], errors="coerce").dropna()
        if vals.empty:
            raise ToolError("value_column har ingen numeriske værdier.")
        counts, edges = np.histogram(vals, bins=params.bins or 20)
        out = pd.DataFrame({
            "bin_start": edges[:-1].round(3), "bin_end": edges[1:].round(3), "count": counts,
        })
        summary.update({"mean": json_value(vals.mean()), "median": json_value(vals.median()),
                        "std": json_value(vals.std()), "skew": json_value(vals.skew())})

    elif op == "top_n":
        if not params.sort_by:
            raise ToolError("top_n kræver sort_by.")
        require_columns(df, params.sort_by)
        out = df.sort_values(params.sort_by, ascending=bool(params.ascending)).head(params.n or 10)

    elif op == "pivot":
        if not (params.pivot_index and params.pivot_columns and params.metrics):
            raise ToolError("pivot kræver pivot_index, pivot_columns og metrics (første bruges).")
        m = params.metrics[0]
        require_columns(df, params.pivot_index, params.pivot_columns, m.column)
        if df[params.pivot_columns].nunique() > 60 or df[params.pivot_index].nunique() > 5000:
            raise ToolError("For mange unikke værdier til pivot. Aggregér eller filtrér først.")
        out = pd.pivot_table(df, index=params.pivot_index, columns=params.pivot_columns, values=m.column,
                             aggfunc=m.agg).reset_index()
        out.columns = [str(c) for c in out.columns]

    elif op == "share":
        if not params.group_by:
            raise ToolError("share kræver group_by.")
        require_columns(df, *params.group_by, params.value_column)
        if params.value_column:
            out = df.groupby(params.group_by, dropna=False)[params.value_column].sum().reset_index(name="value")
        else:
            out = df.groupby(params.group_by, dropna=False).size().reset_index(name="value")
        total = out["value"].sum()
        out["share_pct"] = (out["value"] / total * 100).round(2) if total else 0.0
        out = out.sort_values("share_pct", ascending=False)

    else:  # pragma: no cover - Literal sikrer gyldige værdier
        raise ToolError(f"Ukendt operation {op}.")

    title = params.title or f"{op} af {src.title}"
    result = store.add(out, title, origin="analysis")
    return result, summary
