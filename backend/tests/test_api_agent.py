import pytest
from fastapi.testclient import TestClient

from app.agent.agent import AgentDeps, ChatRequest, HistoryMessage, _history_messages, run_agent
from app.agent.llm import LLMError, ToolUse, Turn
from app.agent.prompts import build_system_prompt
from app.main import create_app
from app.tools.ml import build_registry
from app.tools.registry import tool_definitions
from tests.conftest import sse_events


def test_health_and_datasets(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["demo"] is True and h["data_source"] == "demo"
    d = client.get("/api/datasets").json()
    assert {t["name"] for t in d["tables"]} == {"meal_events", "pantry_items"}
    assert {f["name"] for f in d["ml_functions"]} >= {"forecast_timeseries", "predict_outcome"}


def test_chat_stream_runs_tools_and_answers(client):
    r = client.post("/api/chat", json={"message": "Hvordan udvikler aktiviteten sig?"})
    assert r.status_code == 200
    events = sse_events(r)
    types = [e["type"] for e in events]
    assert types[0] == "start" and events[0]["demo"] is True
    assert {"step", "sql", "chart", "table", "step_done", "text_delta"} <= set(types)
    assert types[-1] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "text_delta")
    assert "[Testtilstand]" in text and "demodata" in text
    assert all(e["ok"] for e in events if e["type"] == "step_done")


def test_chat_validates_input(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 5000}).status_code == 422


def test_access_token_required_when_configured(settings):
    settings.app_access_token = "s3cret"
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/datasets").status_code == 401
        assert c.get("/api/datasets", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/datasets", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_rate_limit(settings):
    settings.rate_limit_per_minute = 2
    with TestClient(create_app(settings)) as c:
        codes = [c.post("/api/chat", json={"message": "hej"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_history_is_normalized():
    msgs = _history_messages([
        HistoryMessage(role="assistant", content="velkommen"),
        HistoryMessage(role="user", content="a"),
        HistoryMessage(role="user", content="b"),
        HistoryMessage(role="assistant", content="svar"),
        HistoryMessage(role="user", content="ubesvaret"),
    ])
    assert msgs == [{"role": "user", "content": "a\n\nb"}, {"role": "assistant", "content": "svar"}]


class RecoveringLLM:
    """Første SQL er usikker; modellen skal se fejlen og prøve igen med en gyldig forespørgsel."""

    def __init__(self):
        self.seen_errors = []

    async def turn(self, *, system, tools, messages, on_text):
        results = [b for m in messages if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]]
        if not results:
            return self._sql("DROP TABLE meal_events", "a")
        if len(results) == 1:
            self.seen_errors.append(results[0])
            return self._sql("SELECT COUNT(*) AS n FROM meal_events", "b")
        await on_text("færdig")
        return Turn([{"type": "text", "text": "færdig"}], "end_turn", [])

    def _sql(self, q, i):
        b = {"type": "tool_use", "id": i, "name": "run_sql", "input": {"sql": q, "title": "x"}}
        return Turn([b], "tool_use", [ToolUse(i, "run_sql", b["input"])])


async def _collect(llm, settings, source):
    registry = build_registry(settings)
    deps = AgentDeps(settings, source, registry, llm, build_system_prompt(source), tool_definitions(registry))
    return [e async for e in run_agent(ChatRequest(message="test"), deps)]


@pytest.mark.anyio
async def test_agent_recovers_from_rejected_sql(settings, source):
    llm = RecoveringLLM()
    events = await _collect(llm, settings, source)
    assert llm.seen_errors[0]["is_error"] is True
    assert "sikkerhedskontrollen" in llm.seen_errors[0]["content"]
    done = [e for e in events if e["type"] == "step_done"]
    assert [d["ok"] for d in done] == [False, True]
    assert events[-1]["type"] == "done"


class FailingLLM:
    async def turn(self, **_):
        raise LLMError("API-nøglen er ugyldig.")


class LoopingLLM:
    async def turn(self, **_):
        b = {"type": "tool_use", "id": "x", "name": "run_sql", "input": {"sql": "SELECT 1 FROM meal_events", "title": "x"}}
        return Turn([b], "tool_use", [ToolUse("x", "run_sql", b["input"])])


@pytest.mark.anyio
async def test_agent_reports_llm_errors(settings, source):
    events = await _collect(FailingLLM(), settings, source)
    assert events[-1] == {"type": "error", "message": "API-nøglen er ugyldig."}


@pytest.mark.anyio
async def test_agent_stops_after_max_steps(settings, source):
    settings.agent_max_steps = 3
    events = await _collect(LoopingLLM(), settings, source)
    assert sum(e["type"] == "step" for e in events) == 3
    assert events[-1]["type"] == "error"


@pytest.mark.anyio
async def test_missing_credentials_give_actionable_error(settings, source, monkeypatch, tmp_path):
    from app.agent.llm import AnthropicLLM

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    settings.anthropic_api_key = ""
    events = await _collect(AnthropicLLM(settings), settings, source)
    assert events[-1]["type"] == "error" and "ANTHROPIC_API_KEY" in events[-1]["message"]


def test_system_prompt_contains_live_schema_and_demo_notice(source):
    prompt = build_system_prompt(source)
    assert "DEMODATA" in prompt and "meal_events" in prompt and "bought_on_offer" in prompt
    assert "wasted" in prompt  # eksempelværdier introspekteret fra data


@pytest.fixture
def anyio_backend():
    return "asyncio"
