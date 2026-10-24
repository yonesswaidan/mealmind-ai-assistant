"""Første vurdering af hvilke værktøjer et spørgsmål kræver (SQL, statistik, ML, prognose, visualisering).

Vurderingen er deterministisk og forklarlig: den vises i UI'et som MealMind Insights' plan og gives til AI-modellen som et
hint. Modellen vælger stadig selv de endelige værktøjskald ud fra data, men kun blandt de godkendte værktøjer,
og den kan ikke træne modeller uden for ML-registret.
"""

import re
from dataclasses import dataclass, field

# Danske (og enkelte engelske) nøgleord pr. type analyse. Matcher på ordstammer.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "forecast": ("prognose", "forudsig", "fremtid", "næste uge", "næste måned", "næste år", "kommende uge",
                 "kommende måned", "forecast", "fremskriv", "forventet udvikling", "hvordan vil"),
    "similarity": ("ligner", "lignende", "minder om", "alternativ til", "erstatte", "i stedet for", "similar",
                   "magen til"),
    "segmentation": ("segment", "gruppér", "grupper brugere", "klynge", "cluster", "brugertyper", "typer af brugere",
                     "persona"),
    "anomaly": ("afvig", "usædvanlig", "anomal", "outlier", "unormal", "ekstrem", "mærkelig", "pludselig"),
    "classification": ("sandsynlighed for", "risiko for", "hvilke faktorer", "hvad forklarer", "hvad driver",
                       "forudsige om", "springes over", "springer over", "churn", "klassific"),
    "statistics": ("gennemsnit", "median", "korrelation", "sammenhæng", "fordeling", "trend", "udvikl",
                   "statistik", "spredning", "andel", "procent", "sammenlign", "forskel", "vækst"),
    "visualization": ("graf", "diagram", "plot", "visualis", "kurve", "søjle", "vis mig", "tegn"),
    "food_waste": ("madspild", "spild", "smidt ud", "smide ud", "kasser"),
}

ML_FUNCTION_FOR = {
    "forecast": "forecast_timeseries",
    "similarity": "find_similar",
    "segmentation": "segment_clusters",
    "anomaly": "detect_anomalies",
    "classification": "predict_outcome",
}

LABELS = {
    "sql": "SQL", "statistics": "Statistik", "forecast": "Prognose", "similarity": "Similarity search",
    "segmentation": "Segmentering", "anomaly": "Afvigelser", "classification": "Klassifikation",
    "visualization": "Visualisering", "food_waste": "Madspild",
}


@dataclass
class AnalysisPlan:
    capabilities: list[str]
    ml_functions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def needs_ml(self) -> bool:
        return bool(self.ml_functions)

    @property
    def has_hint(self) -> bool:
        """Simple opslag (kun SQL) behøver intet hint."""
        return self.capabilities != ["sql"] or bool(self.notes)

    @property
    def tools(self) -> list[str]:
        tools = ["run_sql"]
        if "statistics" in self.capabilities:
            tools.append("analyze_data")
        if self.needs_ml:
            tools.append("run_ml")
        if "visualization" in self.capabilities:
            tools.append("create_chart")
        return tools

    def event(self) -> dict:
        return {"type": "plan", "capabilities": self.capabilities, "labels": [LABELS[c] for c in self.capabilities],
                "tools": self.tools, "ml_functions": self.ml_functions, "notes": self.notes}

    def hint(self) -> str:
        parts = [f"Foreløbig vurdering af spørgsmålet: {', '.join(LABELS[c] for c in self.capabilities)}."]
        if self.ml_functions:
            parts.append(f"Relevante ML-funktioner: {', '.join(self.ml_functions)} - brug dem kun hvis data er "
                         "tilstrækkelige, og forklar ellers hvorfor.")
        parts += self.notes
        parts.append("Afvig fra vurderingen, hvis data eller spørgsmålet kræver det.")
        return "[Systemhint til analysen - ikke skrevet af brugeren] " + " ".join(parts)


def _matches(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(w), text) for w in words)


def plan_question(question: str, available_ml: list[str] | None = None) -> AnalysisPlan:
    text = " ".join(question.casefold().split())
    found = [cap for cap, words in KEYWORDS.items() if _matches(text, words)]
    caps = ["sql"] + [c for c in found if c != "food_waste"]
    ml = [ML_FUNCTION_FOR[c] for c in caps if c in ML_FUNCTION_FOR]
    if available_ml is not None:
        ml = [f for f in ml if f in available_ml]
    if any(c in caps for c in ("forecast", "anomaly")) or ("statistics" in caps and "udvikl" in text):
        if "visualization" not in caps:
            caps.append("visualization")  # udviklinger og prognoser forstås bedst som graf
    notes = []
    if "food_waste" in found:
        caps.append("food_waste")
        notes.append("Madspild: tjek først om datasættene faktisk indeholder registreringer af spild "
                     "(fx en status/hændelse for 'smidt ud'). Udløbsdatoer er ikke spild. Mangler data, så sig det, "
                     "og opfind ikke tal.")
    if "classification" in caps or "segmentation" in caps:
        notes.append("Tjek om tabellen ml_model_status findes; den forklarer hvilke modeller Databricks har trænet.")
    return AnalysisPlan(caps, ml, notes)
