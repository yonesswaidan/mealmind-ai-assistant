import math
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd


class ToolError(ValueError):
    """Fejl som modellen kan rette selv (forkert kolonne, ugyldig parameter osv.)."""


@dataclass
class StoredResult:
    id: str
    df: pd.DataFrame
    title: str
    origin: str
    sql: str | None = None


class ResultStore:
    """Resultater fra én samtaletur. Modellen refererer til dem via id, så store tabeller ikke sendes frem og tilbage."""

    def __init__(self, max_results: int = 40):
        self._results: dict[str, StoredResult] = {}
        self._max = max_results

    def add(self, df: pd.DataFrame, title: str, origin: str, sql: str | None = None) -> StoredResult:
        if len(self._results) >= self._max:
            raise ToolError("For mange mellemresultater i denne tur. Saml analysen i færre trin.")
        rid = f"r{len(self._results) + 1}"
        result = StoredResult(rid, df.reset_index(drop=True), title, origin, sql)
        self._results[rid] = result
        return result

    def get(self, rid: str) -> StoredResult:
        if rid not in self._results:
            known = ", ".join(self._results) or "ingen"
            raise ToolError(f"Ukendt result_id '{rid}'. Kendte resultater: {known}.")
        return self._results[rid]


def json_value(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat() if not pd.isna(v) else None
    if isinstance(v, date):
        return v.isoformat()
    if v is pd.NaT:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v if isinstance(v, (int, str)) else str(v)


def to_records(df: pd.DataFrame, limit: int) -> list[dict]:
    return [{c: json_value(v) for c, v in row.items()} for row in df.head(limit).to_dict(orient="records")]


def describe_result(result: StoredResult, preview_rows: int) -> dict:
    df = result.df
    return {
        "result_id": result.id,
        "title": result.title,
        "row_count": len(df),
        "columns": [{"name": c, "dtype": str(t)} for c, t in df.dtypes.items()],
        "preview": to_records(df, preview_rows),
    }


def require_columns(df: pd.DataFrame, *cols: str | None) -> None:
    missing = [c for c in cols if c and c not in df.columns]
    if missing:
        raise ToolError(f"Kolonne(r) findes ikke: {', '.join(missing)}. Tilgængelige: {', '.join(map(str, df.columns))}.")
