"""Data til hjemmesidens overblik: datakilder, foreslåede spørgsmål og ML-status.

Alt udledes af de tabeller og kolonner, der faktisk findes i datakilden, så forslagene passer til både
demodata, et lokalt udtræk og Databricks. ML-status læses fra gold.ml_model_status, når den tabel findes.
"""

import logging

from app.data.sources import DataSource, QueryError, TableInfo
from app.security.sql_guard import UnsafeQueryError, validate_sql
from app.tools.ml import MLFunction

log = logging.getLogger("insights")

SOURCE_TITLES = {
    "meal_events": ("Måltider", "meals"),
    "shopping_food_items": ("Indkøb og køkkenskab", "shopping"),
    "pantry_items": ("Køkkenskab", "shopping"),
    "meal_similarity": ("Lignende retter (ML)", "ml"),
    "ml_model_status": ("ML-modelstatus", "ml"),
    "user_segments": ("Brugersegmenter (ML)", "ml"),
    "user_segment_profiles": ("Segmentprofiler (ML)", "ml"),
    "planned_meal_skip_risk": ("Risiko for sprungne måltider (ML)", "ml"),
    "daily_intake_anomalies": ("Afvigelser i kalorieindtag (ML)", "ml"),
}

MODEL_TITLES = {
    "meal_similarity": "Lignende retter",
    "user_segments": "Brugersegmenter",
    "meal_skip_classifier": "Sprungne måltider",
    "daily_intake_anomalies": "Afvigelser i kalorier",
    "weekly_meal_forecast": "Prognoser",
    "food_waste_prediction": "Madspild",
}
LOCAL_ML = [
    ("find_similar", "Lignende retter"),
    ("forecast_timeseries", "Prognoser"),
    ("detect_anomalies", "Afvigelser"),
    ("segment_clusters", "Brugersegmenter"),
]
STATUS_LABELS = {
    "trained": "Klar",
    "insufficient_data": "For lidt data",
    "insufficient_signal": "Intet tydeligt mønster",
    "not_available": "Ikke muligt",
    "ready_on_demand": "På forespørgsel",
}


def data_origin(source: DataSource) -> str:
    return "demo" if source.is_demo else "real"


def _find(tables: list[TableInfo], short: str) -> TableInfo | None:
    return next((t for t in tables if t.short_name == short), None)


def _columns(table: TableInfo | None) -> dict:
    return {c.name: c for c in table.columns} if table else {}


def sources(source: DataSource) -> list[dict]:
    origin = data_origin(source)
    out = []
    for t in source.tables():
        title, kind = SOURCE_TITLES.get(t.short_name, (t.short_name.replace("_", " ").capitalize(), "other"))
        out.append({"table": t.name, "title": title, "kind": kind, "rows": t.row_count, "origin": origin,
                    "description": t.description})
    order = {"meals": 0, "shopping": 1, "ml": 2, "other": 3}
    return sorted(out, key=lambda s: (order[s["kind"]], s["title"]))


def suggestions(source: DataSource) -> tuple[list[dict], list[str]]:
    """Hurtige handlinger (chips) og 'næste gode spørgsmål' tilpasset datakildens kolonner."""
    tables = source.tables()
    meals = _find(tables, "meal_events")
    shop = _find(tables, "shopping_food_items") or _find(tables, "pantry_items")
    meal_cols, shop_cols = _columns(meals), _columns(shop)
    has_gold_similarity = _find(tables, "meal_similarity") is not None

    chips: list[dict] = []
    following: list[str] = []
    if meals:
        chips.append({"label": "Vis ugens overblik", "icon": "chart",
                      "question": "Giv mig et overblik over den seneste uge med data: antal måltider pr. dag "
                                  "fordelt på status, vist som graf."})
        chips.append({"label": "Find afvigelser", "icon": "search",
                      "question": "Var der dage med usædvanligt mange eller få registrerede måltider?"})
        names = meal_cols.get("meal_name").sample_values if "meal_name" in meal_cols else []
        dish = names[0] if names else None
        similar_q = (f"Hvilke retter ligner {dish} mest?" if dish else "Hvilke retter ligner hinanden mest?")
        if has_gold_similarity:
            similar_q += " Brug den trænede model i meal_similarity."
        chips.append({"label": "Find lignende retter", "icon": "dish", "question": similar_q})
        if "status" in meal_cols:
            following.append("Hvilke måltider bliver oftest sprunget over?")
        if "calories_kcal" in meal_cols or "calories" in meal_cols:
            following.append("Hvordan fordeler kalorierne sig pr. måltidstype?")
        following.append("Lav en prognose for antal måltider de næste 4 uger.")
    if shop and ("expiry_date" in shop_cols or "expiry_status" in shop_cols):
        following.insert(0, "Hvilke varer udløber snart?")
    if shop and ("category" in shop_cols):
        following.append("Hvilke varekategorier fylder mest?")
    if not chips:
        chips.append({"label": "Hvad indeholder data?", "icon": "chart",
                      "question": "Hvilke tabeller og kolonner er tilgængelige, og hvad kan jeg spørge om?"})
    return chips, following[:5]


def _gold_status(source: DataSource) -> list[dict] | None:
    table = _find(source.tables(), "ml_model_status")
    if table is None:
        return None
    cols = _columns(table)
    wanted = [c for c in ("model_name", "status", "reason", "production_ready", "data_origin") if c in cols]
    try:
        query = validate_sql(f"SELECT {', '.join(wanted)} FROM {table.name}", allowed_tables=[table.name],
                             dialect=source.dialect, row_limit=50)
        df = source.run(query)
    except (QueryError, UnsafeQueryError) as e:
        log.warning("ML-status kunne ikke læses: %s", e)
        return None
    out = []
    for r in df.to_dict(orient="records"):
        synthetic = str(r.get("data_origin", "")) == "synthetic" or source.is_demo
        status = str(r.get("status", ""))
        label = STATUS_LABELS.get(status, status)
        if status == "trained":
            label = "Demo" if synthetic else ("Klar" if r.get("production_ready") else "Afprøvning")
        out.append({"name": r.get("model_name"), "title": MODEL_TITLES.get(r.get("model_name"), r.get("model_name")),
                    "status": status, "label": label, "detail": r.get("reason") or "", "source": "databricks"})
    return out


def ml_status(source: DataSource, registry: dict[str, MLFunction]) -> list[dict]:
    gold = _gold_status(source)
    if gold is not None:
        return gold
    demo = source.is_demo
    return [{"name": fn, "title": title, "status": "on_demand", "label": "Demo" if demo else "På forespørgsel",
             "detail": "Beregnes af MealMind Insights på de hentede data, når du spørger. "
                       + ("Resultater på demodata er ikke produktionsklare." if demo else
                          "Ad hoc-analyse, ikke en registreret produktionsmodel."),
             "source": "local"}
            for fn, title in LOCAL_ML if fn in registry]


def build_overview(source: DataSource, registry: dict[str, MLFunction]) -> dict:
    chips, following = suggestions(source)
    return {
        "data_source": source.kind,
        "data_label": source.label,
        "demo": source.is_demo,
        "sources": sources(source),
        "quick_actions": chips,
        "next_questions": following,
        "ml_status": ml_status(source, registry),
    }
