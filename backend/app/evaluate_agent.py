"""Evaluerer om AI-agenten vælger de rigtige værktøjer: `python -m app.evaluate_agent [--json rapport.json]`.

Kører et fast sæt spørgsmål mod den konfigurerede AI-model og datakilde (fra .env) og kontrollerer, at agenten
bruger SQL, statistik, ML og grafer, hvor det forventes – og at hvert svar bygger på hentede data.
Bruger rigtige API-kald (koster tokens). Med INSIGHTS_TEST_MODE=1 køres et scriptet forløb uden API-nøgle.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field

from app.agent.agent import AgentDeps, ChatRequest, HistoryMessage, run_agent
from app.agent.llm import create_llm, credentials_available
from app.agent.prompts import build_system_prompt
from app.config import Settings, get_settings
from app.data.sources import create_source
from app.tools.ml import build_registry
from app.tools.registry import tool_definitions


@dataclass
class Case:
    question: str
    # Mindst ét værktøj fra hver gruppe skal være brugt. "ml:<funktion>" kræver en bestemt ML-funktion.
    require: list[list[str]]
    forbid: list[str] = field(default_factory=list)
    history: list[tuple[str, str]] = field(default_factory=list)


CASES = [
    Case("Hvor mange måltider er registreret pr. måned?", [["run_sql"]], forbid=["run_ml"]),
    Case("Hvad er gennemsnit og spredning af kalorier pr. måltidstype?", [["run_sql"]], forbid=["run_ml"]),
    Case("Vis en graf over udviklingen i antal måltider pr. uge.", [["run_sql"], ["create_chart"]]),
    Case("Lav en prognose for antal måltider de næste 4 uger.", [["run_sql"], ["ml:forecast_timeseries"]]),
    Case("Var der dage med usædvanligt mange eller få måltider?", [["run_sql"], ["ml:detect_anomalies"]]),
    Case("Hvilke retter ligner hinanden mest?", [["run_sql"], ["ml:find_similar", "run_sql"]]),
    Case("Kan brugerne opdeles i grupper efter deres adfærd?", [["run_sql"], ["ml:segment_clusters", "run_sql"]]),
    Case("Og hvordan ser det ud for aftensmad alene?", [["run_sql"]],
         history=[("Hvor mange måltider er registreret pr. måltidstype?",
                   "Jeg talte måltiderne pr. måltidstype med en SQL-forespørgsel.")]),
]


@dataclass
class CaseResult:
    question: str
    tools: list[str]
    passed: bool
    problems: list[str]
    answer_preview: str


def _used(events: list[dict]) -> list[str]:
    used = []
    for e in events:
        if e["type"] == "step":
            fn = e["input"].get("function") if isinstance(e.get("input"), dict) else None
            used.append(f"ml:{fn}" if e["tool"] == "run_ml" and fn else e["tool"])
    return used


def check(case: Case, events: list[dict]) -> CaseResult:
    used = _used(events)
    tools = set(used) | {"run_ml" for u in used if u.startswith("ml:")}
    problems = [f"mangler et af {group}" for group in case.require if not tools & set(group)]
    problems += [f"brugte {f} uden grund" for f in case.forbid if f in tools]
    if any(e["type"] == "error" for e in events):
        problems.append(next(e["message"] for e in events if e["type"] == "error"))
    if any(e["type"] == "notice" for e in events):
        problems.append("svaret indeholdt tal uden hentede data")
    answer = "".join(e.get("text", "") for e in events if e["type"] == "text_delta")
    return CaseResult(case.question, used, not problems, problems, answer[:160].replace("\n", " "))


async def evaluate(settings: Settings, cases: list[Case] = CASES) -> list[CaseResult]:
    source = create_source(settings)
    registry = build_registry(settings)
    if settings.assistant_test_mode:
        from app.agent.scripted import ScriptedLLM
        llm = ScriptedLLM(source)
    else:
        llm = create_llm(settings)
    deps = AgentDeps(settings, source, registry, llm, build_system_prompt(source), tool_definitions(registry))
    results = []
    for case in cases:
        history = [HistoryMessage(role=r, content=c) for q, a in case.history for r, c in (("user", q), ("assistant", a))]
        events = [e async for e in run_agent(ChatRequest(message=case.question, history=history), deps)]
        results.append(check(case, events))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="Gem resultaterne som JSON")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.assistant_test_mode and not credentials_available(settings):
        print("AI-nøgle mangler (OPENAI_API_KEY). Sæt den i .env eller brug INSIGHTS_TEST_MODE=1.", file=sys.stderr)
        return 2
    results = asyncio.run(evaluate(settings))
    for r in results:
        print(f"{'OK ' if r.passed else 'FEJL'} {r.question}\n     værktøjer: {', '.join(r.tools) or '-'}")
        for p in r.problems:
            print(f"     - {p}")
    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} spørgsmål bestået ({settings.llm_model if not settings.assistant_test_mode else 'testtilstand'}).")
    if args.json:
        with open(args.json, "w") as f:
            json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
