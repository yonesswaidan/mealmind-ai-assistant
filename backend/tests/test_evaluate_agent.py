import pytest

from app.evaluate_agent import CASES, Case, check, evaluate


def step(tool, function=None):
    return {"type": "step", "id": tool, "tool": tool, "input": {"function": function} if function else {}}


def test_check_requires_and_forbids_tools():
    case = Case("prognose", [["run_sql"], ["ml:forecast_timeseries"]], forbid=["create_table"])
    ok = check(case, [step("run_sql"), step("run_ml", "forecast_timeseries"), {"type": "done"}])
    assert ok.passed and ok.tools == ["run_sql", "ml:forecast_timeseries"]
    wrong_ml = check(case, [step("run_sql"), step("run_ml", "segment_clusters")])
    assert not wrong_ml.passed and "ml:forecast_timeseries" in wrong_ml.problems[0]
    plain = Case("tæl", [["run_sql"]], forbid=["run_ml"])
    assert not check(plain, [step("run_sql"), step("run_ml", "detect_anomalies")]).passed
    ungrounded = check(plain, [step("run_sql"), {"type": "notice", "message": "x"}])
    assert not ungrounded.passed and "uden hentede data" in ungrounded.problems[0]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_evaluation_runs_end_to_end_in_test_mode(settings):
    results = await evaluate(settings)
    assert len(results) == len(CASES)
    by_q = {r.question: r for r in results}
    assert by_q[CASES[0].question].passed  # simpelt opslag: kun SQL
    forecast = by_q["Lav en prognose for antal måltider de næste 4 uger."]
    assert forecast.passed and "ml:forecast_timeseries" in forecast.tools
