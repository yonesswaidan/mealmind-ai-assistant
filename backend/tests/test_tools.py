import json

import pytest


def run(executor, name, args):
    out = executor.execute(name, args)
    return out, (json.loads(out.content) if not out.is_error else out.content)


def sql(executor, query, title="t"):
    out, data = run(executor, "run_sql", {"sql": query, "title": title})
    assert not out.is_error, data
    return data


def test_run_sql_returns_preview_and_event(executor):
    data = sql(executor, "SELECT city, COUNT(*) AS n FROM meal_events GROUP BY city ORDER BY n DESC")
    assert data["result_id"] == "r1"
    assert data["row_count"] == 5
    assert data["preview"][0]["city"] == "København"
    assert "LIMIT" in data["executed_sql"]


def test_run_sql_rejects_writes_with_error_result(executor):
    out, msg = run(executor, "run_sql", {"sql": "DELETE FROM meal_events", "title": "x"})
    assert out.is_error and "sikkerhedskontrollen" in msg


def test_run_sql_reports_database_errors(executor):
    out, msg = run(executor, "run_sql", {"sql": "SELECT no_such_col FROM meal_events", "title": "x"})
    assert out.is_error and "no_such_col" in msg


@pytest.mark.parametrize("args", [
    {"operation": "summary_stats", "columns": ["calories", "cost_dkk"]},
    {"operation": "group_aggregate", "group_by": ["plan_source"],
     "metrics": [{"column": "calories", "agg": "mean"}, {"column": "event_id", "agg": "count", "alias": "n"}],
     "sort_by": "n"},
    {"operation": "correlation", "columns": ["calories", "protein_g", "cost_dkk"]},
    {"operation": "trend", "date_column": "event_date", "value_column": "cost_dkk", "freq": "M"},
    {"operation": "distribution", "value_column": "calories", "bins": 10},
    {"operation": "top_n", "sort_by": "cost_dkk", "n": 5},
    {"operation": "pivot", "pivot_index": "city", "pivot_columns": "meal_type",
     "metrics": [{"column": "cost_dkk", "agg": "mean"}]},
    {"operation": "share", "group_by": ["status"]},
])
def test_analysis_operations(executor, args):
    sql(executor, "SELECT * FROM meal_events WHERE event_date >= DATE '2026-06-01'")
    out, data = run(executor, "analyze_data", {"result_id": "r1", **args})
    assert not out.is_error, data
    assert data["row_count"] > 0


def test_trend_detects_growth(executor):
    sql(executor, "SELECT event_date, COUNT(*) AS n FROM meal_events GROUP BY 1")
    _, data = run(executor, "analyze_data", {"result_id": "r1", "operation": "trend", "date_column": "event_date",
                                             "value_column": "n", "freq": "M"})
    assert data["summary"]["slope_per_period"] > 0


def test_analysis_bad_column_is_recoverable_error(executor):
    sql(executor, "SELECT city FROM meal_events LIMIT 10")
    out, msg = run(executor, "analyze_data", {"result_id": "r1", "operation": "summary_stats", "columns": ["nope"]})
    assert out.is_error and "nope" in msg


def test_unknown_result_id(executor):
    out, msg = run(executor, "show_table", {"result_id": "r9", "title": "x"})
    assert out.is_error and "r9" in msg


def test_ml_forecast(executor):
    sql(executor, "SELECT event_date, SUM(cost_dkk) AS cost FROM meal_events GROUP BY 1")
    out, data = run(executor, "run_ml", {"function": "forecast_timeseries", "params": {
        "result_id": "r1", "date_column": "event_date", "value_column": "cost", "freq": "W", "horizon": 6}})
    assert not out.is_error, data
    s = data["summary"]
    assert s["horizon"] == 6 and s["backtest_mape_pct"] is not None
    assert out.events[0]["type"] == "ml"


def test_ml_segments_users(executor):
    sql(executor, """SELECT user_id, COUNT(*) AS meals, AVG(calories) AS kcal,
                     AVG(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skip_rate
                     FROM meal_events GROUP BY user_id""")
    out, data = run(executor, "run_ml", {"function": "segment_clusters", "params": {
        "result_id": "r1", "feature_columns": ["meals", "kcal", "skip_rate"], "id_column": "user_id"}})
    assert not out.is_error, data
    assert 2 <= data["summary"]["n_clusters"] <= 6
    assert len(data["results"]) == 2


def test_ml_anomalies(executor):
    sql(executor, "SELECT event_date, COUNT(*) AS n FROM meal_events GROUP BY 1 ORDER BY 1")
    out, data = run(executor, "run_ml", {"function": "detect_anomalies", "params": {
        "result_id": "r1", "value_column": "n", "date_column": "event_date"}})
    assert not out.is_error, data
    assert data["summary"]["rows_checked"] > 200


def test_ml_predicts_waste_with_signal(executor):
    sql(executor, "SELECT item_id, category, quantity, bought_on_offer, household_size, store, status "
                  "FROM pantry_items")
    out, data = run(executor, "run_ml", {"function": "predict_outcome", "params": {
        "result_id": "r1", "target_column": "status", "positive_value": "wasted",
        "feature_columns": ["category", "quantity", "bought_on_offer", "household_size", "store"],
        "score_where_target_equals": "in_stock", "id_columns": ["item_id"]}})
    assert not out.is_error, data
    s = data["summary"]
    assert s["test_auc"] > 0.65  # demodata har indbygget signal
    assert s["scored"]["rows_scored"] > 0


def test_ml_invalid_params(executor):
    sql(executor, "SELECT city FROM meal_events LIMIT 5")
    out, msg = run(executor, "run_ml", {"function": "forecast_timeseries", "params": {"result_id": "r1"}})
    assert out.is_error and "Ugyldige parametre" in msg
    out, msg = run(executor, "run_ml", {"function": "nope", "params": {}})
    assert out.is_error and "Ukendt ML-funktion" in msg


def test_chart_and_table_events(executor):
    sql(executor, "SELECT date_trunc('month', event_date) AS month, city, COUNT(*) AS n "
                  "FROM meal_events GROUP BY 1, 2 ORDER BY 1")
    out, _ = run(executor, "create_chart", {"result_id": "r1", "chart_type": "line", "x": "month", "y": ["n"],
                                            "series_column": "city", "title": "Måltider pr. by"})
    chart = out.events[0]["chart"]
    assert set(chart["y"]) == {"København", "Aarhus", "Odense", "Aalborg", "Esbjerg"}
    assert chart["data"][0]["month"].startswith("2026-01")

    out, _ = run(executor, "show_table", {"result_id": "r1", "title": "Tabel", "max_rows": 3})
    table = out.events[0]["table"]
    assert len(table["rows"]) == 3 and table["total_rows"] > 3 and table["sql"]


def test_chart_rejects_non_numeric_y(executor):
    sql(executor, "SELECT city, meal_name FROM meal_events LIMIT 20")
    out, msg = run(executor, "create_chart", {"result_id": "r1", "chart_type": "bar", "x": "city",
                                              "y": ["meal_name"], "title": "x"})
    assert out.is_error and "numerisk" in msg


def test_ml_rejects_id_like_features(executor):
    sql(executor, "SELECT item_id, CAST(item_id AS VARCHAR) AS item_code, status FROM pantry_items")
    out, msg = run(executor, "run_ml", {"function": "predict_outcome", "params": {
        "result_id": "r1", "target_column": "status", "positive_value": "wasted", "feature_columns": ["item_code"]}})
    assert out.is_error and "item_code" in msg


def test_pivot_rejects_high_cardinality(executor):
    sql(executor, "SELECT user_id, item_id, price_dkk FROM pantry_items")
    out, msg = run(executor, "analyze_data", {"result_id": "r1", "operation": "pivot", "pivot_index": "user_id",
                                              "pivot_columns": "item_id",
                                              "metrics": [{"column": "price_dkk", "agg": "sum"}]})
    assert out.is_error and "pivot" in msg
