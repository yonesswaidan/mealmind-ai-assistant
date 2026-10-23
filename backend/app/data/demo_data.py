"""Genererer to syntetiske MealMind-datasæt i en lokal DuckDB-fil.

Alt indhold er DEMODATA: tilfældigt genereret med fast seed, så resultaterne er reproducerbare.
Datasættene erstattes af de rigtige Databricks-tabeller, når de er tilgængelige.
"""

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SEED = 20261023
START = date(2026, 1, 1)
END = date(2026, 9, 30)
N_USERS = 300

CITIES = ["København", "Aarhus", "Odense", "Aalborg", "Esbjerg"]
CITY_P = [0.40, 0.22, 0.15, 0.13, 0.10]
DIETS = ["omnivore", "vegetarian", "pescetarian", "vegan", "low_carb"]
DIET_P = [0.58, 0.16, 0.10, 0.06, 0.10]

# (navn, måltidstype, køkken, kcal, protein_g, pris_dkk, egnet til diæter)
MEALS = [
    ("Havregrød med bær", "breakfast", "nordisk", 380, 12, 9, "all"),
    ("Skyr med granola", "breakfast", "nordisk", 350, 24, 14, "nonvegan"),
    ("Rugbrød med æg", "breakfast", "nordisk", 420, 20, 12, "nonvegan"),
    ("Smoothie bowl", "breakfast", "international", 330, 9, 18, "all"),
    ("Omelet med spinat", "breakfast", "fransk", 400, 26, 15, "nonvegan"),
    ("Rugbrød med kylling", "lunch", "nordisk", 520, 34, 28, "meat"),
    ("Linsesalat", "lunch", "middelhav", 480, 22, 22, "all"),
    ("Tunsalat-wrap", "lunch", "international", 510, 31, 30, "fish"),
    ("Falafel pita", "lunch", "mellemøst", 560, 18, 26, "all"),
    ("Kyllingesuppe", "lunch", "nordisk", 430, 30, 24, "meat"),
    ("Pasta med grøntsager", "dinner", "italiensk", 650, 20, 32, "all"),
    ("Laks med kartofler", "dinner", "nordisk", 700, 42, 65, "fish"),
    ("Kylling i karry", "dinner", "indisk", 720, 45, 48, "meat"),
    ("Chili sin carne", "dinner", "mexicansk", 610, 24, 34, "all"),
    ("Frikadeller med kartofler", "dinner", "nordisk", 780, 38, 52, "meat"),
    ("Tofu wok", "dinner", "asiatisk", 590, 28, 40, "all"),
    ("Bøf med salat", "dinner", "international", 690, 48, 78, "meat_lowcarb"),
    ("Grøntsagslasagne", "dinner", "italiensk", 640, 26, 38, "nonvegan"),
    ("Fiskefrikadeller", "dinner", "nordisk", 620, 34, 44, "fish"),
    ("Nudelsuppe med kylling", "dinner", "asiatisk", 560, 32, 36, "meat"),
]

# (ingrediens, kategori, holdbarhed_dage, enhed, pris_dkk, basis-spildrisiko)
INGREDIENTS = [
    ("mælk", "mejeri", 8, "L", 12, 0.22),
    ("yoghurt", "mejeri", 14, "stk", 18, 0.18),
    ("ost", "mejeri", 30, "stk", 35, 0.08),
    ("salat", "grønt", 5, "stk", 15, 0.38),
    ("tomater", "grønt", 7, "bakke", 20, 0.26),
    ("agurk", "grønt", 7, "stk", 9, 0.24),
    ("spinat", "grønt", 4, "pose", 18, 0.40),
    ("æbler", "frugt", 21, "kg", 22, 0.12),
    ("bananer", "frugt", 6, "kg", 16, 0.30),
    ("bær", "frugt", 4, "bakke", 30, 0.36),
    ("rugbrød", "brød", 6, "stk", 25, 0.20),
    ("kyllingebryst", "kød", 4, "pakke", 55, 0.17),
    ("hakket oksekød", "kød", 3, "pakke", 45, 0.15),
    ("laks", "fisk", 3, "pakke", 70, 0.19),
    ("æg", "æg", 28, "bakke", 28, 0.06),
    ("pasta", "tørvarer", 365, "pose", 14, 0.01),
    ("ris", "tørvarer", 365, "pose", 18, 0.01),
    ("linser", "tørvarer", 365, "pose", 20, 0.02),
    ("tofu", "plantebaseret", 10, "pakke", 24, 0.20),
    ("frosne ærter", "frost", 180, "pose", 15, 0.02),
]
STORES = ["Netto", "Bilka", "Føtex", "Rema 1000", "Lidl"]
STORE_P = [0.30, 0.22, 0.18, 0.18, 0.12]


def _diet_ok(tag: str, diet: str) -> bool:
    if tag == "all":
        return True
    if diet == "vegan":
        return False
    if diet == "vegetarian":
        return tag == "nonvegan"
    if diet == "pescetarian":
        return tag in ("nonvegan", "fish")
    if diet == "low_carb":
        return tag in ("meat", "fish", "meat_lowcarb", "nonvegan")
    return True


def _users(rng: np.random.Generator) -> pd.DataFrame:
    days = (END - START).days
    # Flere tilmeldinger over tid, så datasættet viser vækst.
    join_offsets = np.sort((rng.beta(1.6, 1.0, N_USERS) * days * 0.9).astype(int))
    return pd.DataFrame({
        "user_id": np.arange(1, N_USERS + 1),
        "city": rng.choice(CITIES, N_USERS, p=CITY_P),
        "diet_type": rng.choice(DIETS, N_USERS, p=DIET_P),
        "household_size": rng.choice([1, 2, 3, 4, 5], N_USERS, p=[0.28, 0.34, 0.16, 0.16, 0.06]),
        "join_date": pd.to_datetime(START) + pd.to_timedelta(join_offsets, unit="D"),
        "engagement": rng.beta(4, 2.5, N_USERS),
    })


def build_meal_events(rng: np.random.Generator, users: pd.DataFrame) -> pd.DataFrame:
    dates = pd.date_range(START, END, freq="D")
    meal_df = pd.DataFrame(MEALS, columns=["meal_name", "meal_type", "cuisine", "calories", "protein_g", "cost_dkk", "tag"])
    rows = []
    for u in users.itertuples():
        active_dates = dates[dates >= u.join_date]
        active = active_dates[rng.random(len(active_dates)) < u.engagement * 0.85]
        options = {mt: meal_df[(meal_df.meal_type == mt) & meal_df.tag.map(lambda t: _diet_ok(t, u.diet_type))]
                   for mt in ("breakfast", "lunch", "dinner")}
        for mt, prob in (("breakfast", 0.7), ("lunch", 0.75), ("dinner", 0.95)):
            d = active[rng.random(len(active)) < prob]
            if len(d) == 0 or options[mt].empty:
                continue
            picks = options[mt].iloc[rng.integers(0, len(options[mt]), len(d))]
            rows.append(pd.DataFrame({
                "user_id": u.user_id,
                "event_date": d,
                "meal_type": mt,
                "meal_name": picks.meal_name.values,
                "cuisine": picks.cuisine.values,
                "base_kcal": picks.calories.values,
                "base_protein": picks.protein_g.values,
                "base_cost": picks.cost_dkk.values * max(1, u.household_size * 0.8),
                "city": u.city,
                "diet_type": u.diet_type,
                "household_size": u.household_size,
            }))
    df = pd.concat(rows, ignore_index=True)
    n = len(df)
    progress = (df.event_date - pd.Timestamp(START)).dt.days / (END - START).days
    weekend = df.event_date.dt.day_of_week >= 5

    # AI-genererede planer vinder frem over tid; swaps er en lille, stabil andel.
    p_ai = 0.25 + 0.45 * progress
    r = rng.random(n)
    df["plan_source"] = np.where(r < p_ai, "ai_plan", np.where(r < p_ai + 0.12, "swap", "manual"))

    skip_p = (0.16 + 0.08 * weekend + 0.06 * (df.meal_type == "breakfast")
              - 0.06 * (df.plan_source == "ai_plan") - 0.05 * progress)
    df["status"] = np.where(rng.random(n) < skip_p.clip(0.02, 0.6), "skipped", "eaten")

    df["calories"] = (df.base_kcal * rng.normal(1, 0.08, n)).round().astype(int)
    df["protein_g"] = (df.base_protein * rng.normal(1, 0.1, n)).round(1)
    df["cost_dkk"] = (df.base_cost * rng.normal(1, 0.07, n) * (1 + 0.04 * progress)).round(2)
    df["event_date"] = df.event_date.dt.date
    df = df.sort_values(["event_date", "user_id", "meal_type"]).reset_index(drop=True)
    df.insert(0, "event_id", np.arange(1, len(df) + 1))
    return df[["event_id", "user_id", "event_date", "meal_type", "meal_name", "cuisine", "calories",
               "protein_g", "cost_dkk", "plan_source", "status", "city", "diet_type", "household_size"]]


def build_pantry_items(rng: np.random.Generator, users: pd.DataFrame) -> pd.DataFrame:
    ing = pd.DataFrame(INGREDIENTS, columns=["ingredient", "category", "shelf_days", "unit", "price", "base_waste"])
    rows = []
    for u in users.itertuples():
        trips = pd.date_range(u.join_date, END, freq=f"{int(rng.integers(3, 6))}D")
        for t in trips:
            k = int(rng.integers(3, 8))
            picks = ing.iloc[rng.choice(len(ing), k, replace=False)]
            rows.append(pd.DataFrame({
                "user_id": u.user_id,
                "household_size": u.household_size,
                "city": u.city,
                "ingredient": picks.ingredient.values,
                "category": picks.category.values,
                "unit": picks.unit.values,
                "shelf_days": picks.shelf_days.values,
                "base_price": picks.price.values,
                "base_waste": picks.base_waste.values,
                "purchase_date": t,
                "store": rng.choice(STORES, p=STORE_P),
                "engagement": u.engagement,
            }))
    df = pd.concat(rows, ignore_index=True)
    n = len(df)
    df["quantity"] = rng.choice([1, 1, 1, 2, 2, 3], n)
    df["bought_on_offer"] = rng.random(n) < 0.27
    df["price_dkk"] = (df.base_price * df.quantity * np.where(df.bought_on_offer, 0.7, 1.0)
                       * rng.normal(1, 0.06, n)).round(2)
    df["expiry_date"] = df.purchase_date + pd.to_timedelta(df.shelf_days, unit="D")

    # Spildrisiko: kort holdbarhed, store mængder, tilbudskøb og single-husstande øger risikoen;
    # engagerede brugere (der følger madplanen) spilder mindre.
    logit = (np.log(df.base_waste / (1 - df.base_waste)) + 0.35 * (df.quantity - 1) + 0.45 * df.bought_on_offer
             + 0.30 * (df.household_size == 1) - 1.1 * (df.engagement - 0.6))
    wasted = rng.random(n) < 1 / (1 + np.exp(-logit))

    ref = pd.Timestamp(END)
    still_open = df.expiry_date > ref
    in_stock = still_open & (rng.random(n) < 0.6)
    df["status"] = np.where(in_stock, "in_stock", np.where(wasted, "wasted", "used"))
    life = (df.expiry_date - df.purchase_date).dt.days.clip(lower=1)
    used_after = (rng.random(n) * life * 0.9).round().astype(int)
    resolved = np.where(df.status == "wasted", df.expiry_date + pd.to_timedelta(1, unit="D"),
                        df.purchase_date + pd.to_timedelta(used_after, unit="D"))
    df["resolved_date"] = pd.Series(resolved).where(df.status != "in_stock")
    df["resolved_date"] = pd.to_datetime(df.resolved_date).clip(upper=ref)

    df = df.sort_values(["purchase_date", "user_id"]).reset_index(drop=True)
    df.insert(0, "item_id", np.arange(1, len(df) + 1))
    for c in ("purchase_date", "expiry_date", "resolved_date"):
        df[c] = pd.to_datetime(df[c]).dt.date
    return df[["item_id", "user_id", "ingredient", "category", "quantity", "unit", "price_dkk", "store",
               "bought_on_offer", "purchase_date", "expiry_date", "status", "resolved_date", "household_size", "city"]]


TABLE_COMMENTS = {
    "meal_events": "DEMODATA: Syntetiske måltidshændelser (planlagte/spiste/sprungne måltider) pr. bruger og dag.",
    "pantry_items": "DEMODATA: Syntetiske køkkenskabsvarer med køb, udløb og om varen blev brugt eller spildt.",
}


def generate(path: Path) -> None:
    rng = np.random.default_rng(SEED)
    users = _users(rng)
    meals = build_meal_events(rng, users)
    pantry = build_pantry_items(rng, users)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.register("meals_df", meals)
        con.register("pantry_df", pantry)
        con.execute("CREATE TABLE meal_events AS SELECT * FROM meals_df")
        con.execute("CREATE TABLE pantry_items AS SELECT * FROM pantry_df")
        for table, comment in TABLE_COMMENTS.items():
            con.execute(f"COMMENT ON TABLE {table} IS '{comment}'")
    finally:
        con.close()
    tmp.replace(path)


def ensure_demo_db(path: Path) -> None:
    if not path.exists():
        generate(path)
