"""Registry af ML-funktioner, som agenten kan vælge imellem.

Lokale funktioner bruger scikit-learn på et tidligere resultat. Databricks Model Serving-endpoints
kan tilføjes via DATABRICKS_ML_ENDPOINTS og vises så som ekstra funktioner.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationError
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import accuracy_score, roc_auc_score, silhouette_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from app.config import Settings
from app.tools.analysis import FREQ_ALIAS
from app.tools.results import ResultStore, StoredResult, ToolError, json_value, require_columns

MAX_CATEGORY_LEVELS = 50


class ForecastParams(BaseModel):
    result_id: str
    date_column: str
    value_column: str
    freq: Literal["D", "W", "M"] = "W"
    horizon: int = Field(default=8, ge=1, le=104)
    agg: Literal["sum", "mean"] = "sum"


class SegmentParams(BaseModel):
    result_id: str
    feature_columns: list[str] = Field(min_length=1, max_length=20)
    id_column: str | None = None
    n_clusters: int | None = Field(default=None, ge=2, le=10)


class AnomalyParams(BaseModel):
    result_id: str
    value_column: str
    date_column: str | None = None
    threshold: float = Field(default=3.5, ge=1.5, le=10)


class OutcomeParams(BaseModel):
    result_id: str
    target_column: str
    positive_value: str | float | bool
    feature_columns: list[str] = Field(min_length=1, max_length=30)
    score_where_target_equals: str | float | bool | None = None
    id_columns: list[str] | None = None


class EndpointParams(BaseModel):
    result_id: str
    columns: list[str] | None = None
    max_rows: int = Field(default=200, ge=1, le=1000)


@dataclass
class MLFunction:
    name: str
    description: str
    params: type[BaseModel]
    run: Callable[[ResultStore, Any], tuple[list[StoredResult], dict]]


def _period_series(df: pd.DataFrame, p: ForecastParams) -> pd.Series:
    s = df[[p.date_column, p.value_column]].copy()
    s[p.date_column] = pd.to_datetime(s[p.date_column], errors="coerce")
    s = s.dropna(subset=[p.date_column])
    grouped = s.set_index(p.date_column)[p.value_column].resample(FREQ_ALIAS[p.freq])
    series = grouped.sum(min_count=1) if p.agg == "sum" else grouped.mean()
    return series.astype(float).interpolate(limit_direction="both")


def _design(index: pd.DatetimeIndex, freq: str, t0: pd.Timestamp, step: pd.Timedelta | None) -> np.ndarray:
    if freq == "M":
        t = (index.year - t0.year) * 12 + (index.month - t0.month)
        season = pd.get_dummies(pd.Categorical(index.month, categories=range(1, 13)), drop_first=True)
    else:
        t = (index - t0) / step
        season = (pd.get_dummies(pd.Categorical(index.day_of_week, categories=range(7)), drop_first=True)
                  if freq == "D" else pd.DataFrame(index=range(len(index))))
    return np.column_stack([np.asarray(t, dtype=float), season.to_numpy(dtype=float)])


def forecast(store: ResultStore, p: ForecastParams):
    src = store.get(p.result_id)
    require_columns(src.df, p.date_column, p.value_column)
    series = _period_series(src.df, p)
    if len(series) < 6:
        raise ToolError("Prognose kræver mindst 6 perioder med data. Brug en finere freq eller mere data.")
    t0 = series.index[0]
    step = (series.index[1] - series.index[0]) if p.freq != "M" else None
    X = _design(series.index, p.freq, t0, step)
    y = series.to_numpy()

    holdout = max(1, len(y) // 5)
    bt = LinearRegression().fit(X[:-holdout], y[:-holdout])
    pred_bt = bt.predict(X[-holdout:])
    mae = float(np.mean(np.abs(pred_bt - y[-holdout:])))
    nonzero = y[-holdout:] != 0
    mape = float(np.mean(np.abs((pred_bt[nonzero] - y[-holdout:][nonzero]) / y[-holdout:][nonzero])) * 100) if nonzero.any() else None

    model = LinearRegression().fit(X, y)
    resid_std = float(np.std(y - model.predict(X), ddof=1))
    future_idx = pd.date_range(series.index[-1], periods=p.horizon + 1, freq=FREQ_ALIAS[p.freq])[1:]
    fut = model.predict(_design(future_idx, p.freq, t0, step))

    out = pd.concat([
        pd.DataFrame({"period": series.index, "actual": y, "forecast": np.nan, "lower": np.nan, "upper": np.nan}),
        pd.DataFrame({"period": future_idx, "actual": np.nan, "forecast": fut,
                      "lower": fut - 1.96 * resid_std, "upper": fut + 1.96 * resid_std}),
    ], ignore_index=True)
    out["period"] = out["period"].dt.date
    result = store.add(out.round(3), f"Prognose: {p.value_column}", origin="ml")
    return [result], {
        "model": "Lineær trend" + (" + sæson" if p.freq in ("D", "M") else ""),
        "history_periods": len(y),
        "horizon": p.horizon,
        "backtest_holdout_periods": holdout,
        "backtest_mae": json_value(mae),
        "backtest_mape_pct": json_value(mape),
        "trend_per_period": json_value(model.coef_[0]),
        "next_period_forecast": json_value(fut[0]),
        "last_period_forecast": json_value(fut[-1]),
        "interval": "≈95% baseret på residualernes spredning",
    }


def segment(store: ResultStore, p: SegmentParams):
    src = store.get(p.result_id)
    require_columns(src.df, *p.feature_columns, p.id_column)
    feats = src.df[p.feature_columns].apply(pd.to_numeric, errors="coerce")
    mask = feats.notna().all(axis=1)
    if mask.sum() < 10:
        raise ToolError("Segmentering kræver mindst 10 rækker med numeriske features.")
    X = StandardScaler().fit_transform(feats[mask])
    rng = np.random.default_rng(0)
    sample = X if len(X) <= 4000 else X[rng.choice(len(X), 4000, replace=False)]

    if p.n_clusters:
        k, scores = p.n_clusters, {}
    else:
        scores = {}
        for k_try in range(2, min(7, len(sample))):
            labels = KMeans(n_clusters=k_try, n_init=10, random_state=0).fit_predict(sample)
            scores[k_try] = float(silhouette_score(sample, labels))
        k = max(scores, key=scores.get)
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)

    assigned = src.df[mask].copy()
    assigned["segment"] = km.labels_
    profile = assigned.groupby("segment")[p.feature_columns].mean().round(3)
    profile.insert(0, "size", assigned.groupby("segment").size())
    profile = profile.reset_index()
    keep = ([p.id_column] if p.id_column else []) + p.feature_columns + ["segment"]
    r_profile = store.add(profile, "Segmentprofiler", origin="ml")
    r_assign = store.add(assigned[keep], "Segmenttildeling", origin="ml")
    overall = feats[mask].mean()
    return [r_profile, r_assign], {
        "model": "KMeans på standardiserede features",
        "n_clusters": k,
        "silhouette_by_k": {str(a): json_value(b) for a, b in scores.items()},
        "rows_used": int(mask.sum()),
        "overall_means": {c: json_value(v) for c, v in overall.items()},
    }


def anomalies(store: ResultStore, p: AnomalyParams):
    src = store.get(p.result_id)
    require_columns(src.df, p.value_column, p.date_column)
    df = src.df.copy()
    vals = pd.to_numeric(df[p.value_column], errors="coerce")
    if p.date_column:
        df = df.assign(_d=pd.to_datetime(df[p.date_column], errors="coerce")).sort_values("_d")
        vals = pd.to_numeric(df[p.value_column], errors="coerce")
        baseline = vals.rolling(7, center=True, min_periods=3).median()
        resid = vals - baseline
        df = df.drop(columns="_d")
    else:
        baseline = pd.Series(vals.median(), index=vals.index)
        resid = vals - baseline
    mad = float(np.median(np.abs(resid.dropna() - np.median(resid.dropna())))) or 1e-9
    z = 0.6745 * resid / mad
    df["expected"] = baseline.round(3)
    df["robust_z"] = z.round(2)
    flagged = df[z.abs() >= p.threshold].sort_values("robust_z", key=abs, ascending=False)
    result = store.add(flagged, f"Afvigelser i {p.value_column}", origin="ml")
    return [result], {
        "method": "Robust z-score (median/MAD)" + (" på afvigelse fra 7-periode rullende median" if p.date_column else ""),
        "threshold": p.threshold,
        "rows_checked": int(vals.notna().sum()),
        "anomalies_found": int(len(flagged)),
    }


def predict_outcome(store: ResultStore, p: OutcomeParams):
    src = store.get(p.result_id)
    require_columns(src.df, p.target_column, *p.feature_columns, *(p.id_columns or []))
    df = src.df
    target = df[p.target_column].astype(str)
    pos = str(p.positive_value)
    score_mask = (target == str(p.score_where_target_equals)) if p.score_where_target_equals is not None \
        else pd.Series(False, index=df.index)
    train = df[~score_mask]
    y = (train[p.target_column].astype(str) == pos).astype(int)
    if y.nunique() < 2:
        raise ToolError(f"Target '{p.target_column}' skal have både '{pos}' og andre værdier i træningsdata.")
    if len(train) < 50:
        raise ToolError("Udfaldsmodel kræver mindst 50 træningsrækker.")

    def features(frame: pd.DataFrame) -> pd.DataFrame:
        f = frame[p.feature_columns].copy()
        for c in f.columns:
            if pd.api.types.is_datetime64_any_dtype(f[c]) or _looks_like_date(f[c]):
                f[c] = pd.to_datetime(f[c], errors="coerce").dt.day_of_year
            elif pd.api.types.is_bool_dtype(f[c]):
                f[c] = f[c].astype(int)
            elif not pd.api.types.is_numeric_dtype(f[c]) and f[c].nunique() > MAX_CATEGORY_LEVELS:
                raise ToolError(f"Feature '{c}' har over {MAX_CATEGORY_LEVELS} forskellige værdier (fx et id). "
                                "Udelad den eller gruppér værdierne først.")
        return pd.get_dummies(f, dummy_na=False)

    X_all = features(df)
    X_train = X_all.loc[train.index]
    X_tr, X_te, y_tr, y_te = train_test_split(X_train, y, test_size=0.25, random_state=0, stratify=y)
    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=0).fit(X_tr, y_tr)
    proba = model.predict_proba(X_te)[:, 1]
    auc = float(roc_auc_score(y_te, proba))
    acc = float(accuracy_score(y_te, proba >= 0.5))

    sub = X_te if len(X_te) <= 2000 else X_te.sample(2000, random_state=0)
    imp = permutation_importance(model, sub, y_te.loc[sub.index], n_repeats=5, random_state=0, scoring="roc_auc")
    importance = pd.DataFrame({"feature": X_te.columns, "importance": imp.importances_mean})
    importance = importance.sort_values("importance", ascending=False).head(15).round(4)
    results = [store.add(importance, "Feature-betydning", origin="ml")]

    rate_by_feature = {}
    for c in p.feature_columns:
        if not pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c]) or df[c].nunique() <= 12:
            rates = train.assign(_y=y).groupby(c)["_y"].mean().sort_values(ascending=False)
            rate_by_feature[c] = {str(k): json_value(v) for k, v in rates.head(6).items()}

    scored_info = None
    if score_mask.any():
        scored = df[score_mask].copy()
        scored["predicted_probability"] = model.predict_proba(X_all.loc[scored.index])[:, 1].round(4)
        keep = (p.id_columns or []) + p.feature_columns + ["predicted_probability"]
        scored = scored[keep].sort_values("predicted_probability", ascending=False)
        results.append(store.add(scored, "Scorede rækker (højeste sandsynlighed først)", origin="ml"))
        scored_info = {"rows_scored": int(len(scored)),
                       "mean_probability": json_value(scored["predicted_probability"].mean()),
                       "rows_above_50pct": int((scored["predicted_probability"] >= 0.5).sum())}

    return results, {
        "model": "Gradient boosting (HistGradientBoostingClassifier)",
        "target": f"{p.target_column} == {pos}",
        "train_rows": int(len(X_tr)),
        "test_rows": int(len(X_te)),
        "base_rate": json_value(y.mean()),
        "test_auc": json_value(auc),
        "test_accuracy_at_0_5": json_value(acc),
        "observed_rate_by_feature_value": rate_by_feature,
        "scored": scored_info,
    }


def _looks_like_date(s: pd.Series) -> bool:
    sample = s.dropna().head(5)
    return len(sample) > 0 and all(hasattr(v, "isoformat") for v in sample)


def _endpoint_runner(settings: Settings, endpoint: str):
    def run(store: ResultStore, p: EndpointParams):
        src = store.get(p.result_id)
        df = src.df[p.columns] if p.columns else src.df
        if p.columns:
            require_columns(src.df, *p.columns)
        records = [{c: json_value(v) for c, v in r.items()} for r in df.head(p.max_rows).to_dict(orient="records")]
        url = f"https://{settings.databricks_server_hostname}/serving-endpoints/{endpoint}/invocations"
        req = urllib.request.Request(
            url, data=json.dumps({"dataframe_records": records}).encode(), method="POST",
            headers={"Authorization": f"Bearer {settings.databricks_token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.sql_timeout_seconds) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise ToolError(f"Model-endpoint '{endpoint}' svarede ikke korrekt: {e}") from e
        preds = body.get("predictions", body)
        out = df.head(p.max_rows).copy()
        out["prediction"] = [json.dumps(x) if isinstance(x, (dict, list)) else x for x in preds][: len(out)]
        return [store.add(out, f"Forudsigelser fra {endpoint}", origin="ml")], {"endpoint": endpoint, "rows": len(out)}
    return run


LOCAL_FUNCTIONS = [
    MLFunction("forecast_timeseries",
               "Prognose for en tidsserie (lineær trend + sæson) med backtest og ≈95%-interval. "
               "Params: result_id, date_column, value_column, freq (D/W/M), horizon, agg (sum/mean).",
               ForecastParams, forecast),
    MLFunction("segment_clusters",
               "Segmentering (KMeans) af rækker, fx brugere, på numeriske features. Vælger selv antal segmenter "
               "via silhouette, hvis n_clusters udelades. Params: result_id, feature_columns, id_column, n_clusters.",
               SegmentParams, segment),
    MLFunction("detect_anomalies",
               "Finder usædvanlige værdier med robust z-score; med date_column måles afvigelse fra rullende median. "
               "Params: result_id, value_column, date_column, threshold.",
               AnomalyParams, anomalies),
    MLFunction("predict_outcome",
               "Træner en klassifikationsmodel for et binært udfald (fx om en vare spildes) og rapporterer AUC og "
               "feature-betydning. Kan score rækker uden kendt udfald (score_where_target_equals, fx 'in_stock'). "
               "Params: result_id, target_column, positive_value, feature_columns, score_where_target_equals, id_columns.",
               OutcomeParams, predict_outcome),
]


def build_registry(settings: Settings) -> dict[str, MLFunction]:
    registry = {f.name: f for f in LOCAL_FUNCTIONS}
    if settings.databricks_ml_endpoints.strip():
        try:
            endpoints = json.loads(settings.databricks_ml_endpoints)
        except json.JSONDecodeError as e:
            raise ValueError("DATABRICKS_ML_ENDPOINTS skal være gyldig JSON.") from e
        for name, cfg in endpoints.items():
            registry[f"endpoint_{name}"] = MLFunction(
                f"endpoint_{name}",
                f"Databricks Model Serving: {cfg.get('description', name)}. Params: result_id, columns, max_rows.",
                EndpointParams, _endpoint_runner(settings, cfg["endpoint"]),
            )
    return registry


def run_ml(registry: dict[str, MLFunction], store: ResultStore, function: str, params: dict):
    if function not in registry:
        raise ToolError(f"Ukendt ML-funktion '{function}'. Tilgængelige: {', '.join(registry)}.")
    fn = registry[function]
    try:
        parsed = fn.params.model_validate(params)
    except ValidationError as e:
        raise ToolError(f"Ugyldige parametre til {function}: {e.errors(include_url=False)}") from e
    return fn.run(store, parsed)
