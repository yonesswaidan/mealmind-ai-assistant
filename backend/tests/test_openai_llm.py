"""Tester OpenAILLM mod en lokal fake Responses API: request-format, streaming, function calling,
samtalehistorik, flere værktøjskald i samme samtale og fejlhåndtering. Kræver ingen rigtig API-nøgle."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.agent.agent import AgentDeps, ChatRequest, HistoryMessage, run_agent
from app.agent.llm import AnthropicLLM, create_llm
from app.agent.openai_llm import OpenAILLM, to_openai_input, to_openai_tools
from app.agent.prompts import build_system_prompt
from app.agent.router import plan_question
from app.main import create_app
from app.tools.ml import build_registry
from app.tools.registry import tool_definitions

TEST_KEY = "sk-test-not-a-real-key"


def message(text: str, i: int = 1) -> dict:
    return {"type": "message", "id": f"msg_{i}", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def function_call(call_id: str, name: str, args: dict | str) -> dict:
    arguments = args if isinstance(args, str) else json.dumps(args)
    return {"type": "function_call", "id": f"fc_{call_id}", "call_id": call_id, "name": name,
            "arguments": arguments, "status": "completed"}


def reasoning(i: int = 1) -> dict:
    return {"type": "reasoning", "id": f"rs_{i}", "summary": [], "encrypted_content": f"enc-{i}"}


def sse_reply(output: list[dict], *, text_chunks: list[str] = (), status: str = "completed",
              incomplete: str | None = None) -> tuple:
    events = [{"type": "response.created", "response": {"id": "resp_1", "status": "in_progress", "output": []}}]
    events += [{"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0, "content_index": 0,
                "delta": chunk, "logprobs": []} for chunk in text_chunks]
    response = {"id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-6.1-sol", "status": status,
                "output": output, "error": None, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
                "incomplete_details": {"reason": incomplete} if incomplete else None}
    events.append({"type": f"response.{status}", "response": response})
    return ("sse", [{**e, "sequence_number": n} for n, e in enumerate(events)])


def error_reply(status: int, code: str, message_text: str = "fejl") -> tuple:
    return ("status", status, {"error": {"message": message_text, "type": "invalid_request_error",
                                         "param": None, "code": code}})


class FakeResponsesApi(BaseHTTPRequestHandler):
    replies: list[tuple] = []
    requests: list[dict] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeResponsesApi.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        reply = FakeResponsesApi.replies.pop(0)
        if reply[0] == "status":
            payload = json.dumps(reply[2]).encode()
            self.send_response(reply[1])
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for event in reply[1]:
            self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_openai(monkeypatch):
    FakeResponsesApi.replies, FakeResponsesApi.requests = [], []
    server = HTTPServer(("127.0.0.1", 0), FakeResponsesApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield FakeResponsesApi
    server.shutdown()


@pytest.fixture
def openai_settings(settings):
    settings.ai_provider = "openai"
    settings.openai_api_key = TEST_KEY
    return settings


def make_llm(settings) -> OpenAILLM:
    llm = OpenAILLM(settings)
    llm._client = llm.client.with_options(max_retries=0)  # fejltests skal ikke vente på SDK'ens backoff
    return llm


async def collect(llm, settings, source, message_text="test", history=()):
    registry = build_registry(settings)
    deps = AgentDeps(settings, source, registry, llm, build_system_prompt(source), tool_definitions(registry))
    request = ChatRequest(message=message_text, history=list(history))
    return [e async for e in run_agent(request, deps)]


@pytest.mark.anyio
async def test_plain_question_streams_text_and_request_format(fake_openai, openai_settings):
    fake_openai.replies = [sse_reply([reasoning(), message("MealMind er en madplan-app.")],
                                     text_chunks=["MealMind ", "er en ", "madplan-app."])]
    texts = []

    async def on_text(t):
        texts.append(t)

    tools = [{"name": "run_sql", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    turn = await make_llm(openai_settings).turn(system="sys", tools=tools,
                                                messages=[{"role": "user", "content": "Hvad er MealMind?"}],
                                                on_text=on_text)

    assert texts == ["MealMind ", "er en ", "madplan-app."]
    assert turn.stop_reason == "end_turn" and turn.tool_uses == []
    assert [b["type"] for b in turn.content] == ["reasoning", "message"]

    req = fake_openai.requests[0]
    body = req["body"]
    assert req["path"] == "/v1/responses"
    assert req["headers"]["authorization"] == f"Bearer {TEST_KEY}"
    assert body["model"] == "gpt-6.1-sol"
    assert body["reasoning"] == {"effort": "medium"}
    assert body["instructions"] == "sys"
    assert body["stream"] is True and body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["input"] == [{"role": "user", "content": "Hvad er MealMind?"}]
    assert body["tools"] == [{"type": "function", "name": "run_sql", "description": "d",
                              "parameters": {"type": "object", "properties": {}}, "strict": False}]


@pytest.mark.anyio
async def test_model_and_effort_are_configurable(fake_openai, openai_settings):
    openai_settings.openai_model = "gpt-anden-model"
    openai_settings.openai_reasoning_effort = "high"
    fake_openai.replies = [sse_reply([message("ok")])]

    async def on_text(_):
        pass

    await make_llm(openai_settings).turn(system="s", tools=[], messages=[{"role": "user", "content": "q"}],
                                         on_text=on_text)
    body = fake_openai.requests[0]["body"]
    assert body["model"] == "gpt-anden-model" and body["reasoning"] == {"effort": "high"}


@pytest.mark.anyio
async def test_full_agent_conversation_with_sql_ml_chart_and_history(fake_openai, openai_settings, source):
    """Flere værktøjskald i samme samtale: SQL → (ML + graf parallelt) → tabel → forklaring."""
    sql = ("SELECT date_trunc('day', event_date) AS day, COUNT(*) AS n FROM meal_events "
           "GROUP BY 1 ORDER BY 1")
    fake_openai.replies = [
        sse_reply([reasoning(1), function_call("call_sql", "run_sql", {"sql": sql, "title": "Hændelser pr. dag"})]),
        sse_reply([reasoning(2),
                   function_call("call_ml", "run_ml", {"function": "forecast_timeseries",
                                                       "params": {"result_id": "r1", "date_column": "day",
                                                                  "value_column": "n", "horizon": 14}}),
                   function_call("call_chart", "create_chart", {"result_id": "r1", "chart_type": "line", "x": "day",
                                                                "y": ["n"], "title": "Hændelser pr. dag"})]),
        sse_reply([function_call("call_table", "show_table", {"result_id": "r1", "title": "Hændelser"})]),
        sse_reply([message("Aktiviteten er stabil (demodata).")], text_chunks=["Aktiviteten er ", "stabil (demodata)."]),
    ]
    history = [HistoryMessage(role="user", content="Hvor mange brugere er der?"),
               HistoryMessage(role="assistant", content="Der er 500 brugere (demodata).")]
    events = await collect(make_llm(openai_settings), openai_settings, source,
                           "Hvordan udvikler aktiviteten sig?", history)

    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done"
    assert [e["tool"] for e in events if e["type"] == "step"] == ["run_sql", "run_ml", "create_chart", "show_table"]
    assert {"sql", "ml", "chart", "table"} <= set(types)
    done = {e["id"]: e for e in events if e["type"] == "step_done"}
    assert done["call_sql"]["ok"] and done["call_chart"]["ok"] and done["call_table"]["ok"]
    assert "".join(e["text"] for e in events if e["type"] == "text_delta") == "Aktiviteten er stabil (demodata)."

    first, second, third = (r["body"]["input"] for r in fake_openai.requests[:3])
    # Samtalehistorikken sendes med som almindelige beskeder før det nye spørgsmål.
    assert first == [{"role": "user", "content": "Hvor mange brugere er der?"},
                     {"role": "assistant", "content": "Der er 500 brugere (demodata)."},
                     {"role": "user", "content": "Hvordan udvikler aktiviteten sig?\n\n"
                                                 + plan_question("Hvordan udvikler aktiviteten sig?").hint()}]
    # Reasoning og function_call sendes retur sammen med værktøjsresultatet for samme call_id.
    assert second[3]["type"] == "reasoning" and second[3]["encrypted_content"] == "enc-1"
    assert second[4]["type"] == "function_call" and second[4]["call_id"] == "call_sql"
    sql_output = second[5]
    assert sql_output["type"] == "function_call_output" and sql_output["call_id"] == "call_sql"
    assert json.loads(sql_output["output"])["result_id"] == "r1"
    # Begge parallelle kald får et output i næste request.
    outputs = [i["call_id"] for i in third if i.get("type") == "function_call_output"]
    assert outputs == ["call_sql", "call_ml", "call_chart"]


@pytest.mark.anyio
async def test_rejected_sql_is_returned_to_model_as_error(fake_openai, openai_settings, source):
    fake_openai.replies = [
        sse_reply([function_call("c1", "run_sql", {"sql": "DROP TABLE meal_events", "title": "x"})]),
        sse_reply([message("Det må jeg ikke.")], text_chunks=["Det må jeg ikke."]),
    ]
    events = await collect(make_llm(openai_settings), openai_settings, source)
    assert [e["ok"] for e in events if e["type"] == "step_done"] == [False]
    output = next(i for i in fake_openai.requests[1]["body"]["input"] if i.get("type") == "function_call_output")
    assert output["output"].startswith("FEJL:") and "sikkerhedskontrollen" in output["output"]
    assert events[-1]["type"] == "done"


@pytest.mark.anyio
async def test_invalid_tool_arguments_are_reported_to_model(fake_openai, openai_settings, source):
    fake_openai.replies = [
        sse_reply([function_call("c1", "run_sql", "{ikke json")]),
        sse_reply([message("Rettet.")]),
    ]
    events = await collect(make_llm(openai_settings), openai_settings, source)
    output = next(i for i in fake_openai.requests[1]["body"]["input"] if i.get("type") == "function_call_output")
    assert "Ugyldigt input" in output["output"]
    assert events[-1]["type"] == "done"


@pytest.mark.anyio
async def test_truncated_answer_gives_error(fake_openai, openai_settings, source):
    fake_openai.replies = [sse_reply([reasoning()], status="incomplete", incomplete="max_output_tokens")]
    events = await collect(make_llm(openai_settings), openai_settings, source)
    assert events[-1]["type"] == "error" and "for langt" in events[-1]["message"]


@pytest.mark.anyio
async def test_refusal_gives_error(fake_openai, openai_settings, source):
    refusal = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
               "content": [{"type": "refusal", "refusal": "Nej."}]}
    fake_openai.replies = [sse_reply([refusal])]
    events = await collect(make_llm(openai_settings), openai_settings, source)
    assert events[-1] == {"type": "error", "message": "AI-modellen afviste at besvare denne forespørgsel."}


@pytest.mark.anyio
@pytest.mark.parametrize("reply, expected", [
    (error_reply(401, "invalid_api_key", f"Incorrect API key provided: {TEST_KEY}"), "API-nøglen er ugyldig"),
    (error_reply(403, "model_not_allowed"), "har ikke adgang til modellen 'gpt-6.1-sol'"),
    (error_reply(404, "model_not_found"), "Modellen 'gpt-6.1-sol' findes ikke"),
    (error_reply(400, "model_not_found"), "Modellen 'gpt-6.1-sol' findes ikke"),
    (error_reply(429, "rate_limit_exceeded"), "rate limit"),
    (error_reply(429, "insufficient_quota"), "ikke mere kredit"),
    (error_reply(500, "server_error"), "fejl (500)"),
])
async def test_api_errors_give_actionable_messages(fake_openai, openai_settings, source, reply, expected):
    fake_openai.replies = [reply]
    events = await collect(make_llm(openai_settings), openai_settings, source)
    assert events[-1]["type"] == "error" and expected in events[-1]["message"]
    assert TEST_KEY not in events[-1]["message"]


@pytest.mark.anyio
async def test_stream_failure_event_gives_error(fake_openai, openai_settings, source):
    _, events = sse_reply([])
    events[-1] = {"type": "response.failed", "sequence_number": 1, "response": {
        "id": "resp_1", "status": "failed", "output": [], "error": {"code": "server_error", "message": "boom"}}}
    fake_openai.replies = [("sse", events)]
    result = await collect(make_llm(openai_settings), openai_settings, source)
    assert result[-1] == {"type": "error", "message": "AI-tjenesten kunne ikke fuldføre svaret. Prøv igen."}


@pytest.mark.anyio
async def test_connection_error(openai_settings, source, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")  # ingen lytter på port 9
    events = await collect(make_llm(openai_settings), openai_settings, source)
    assert events[-1] == {"type": "error", "message": "Kunne ikke forbinde til AI-tjenesten. Tjek netværket."}


@pytest.mark.anyio
async def test_missing_key_gives_actionable_error(fake_openai, openai_settings, source):
    openai_settings.openai_api_key = ""
    events = await collect(OpenAILLM(openai_settings), openai_settings, source)
    assert events[-1]["type"] == "error" and "OPENAI_API_KEY" in events[-1]["message"]
    assert fake_openai.requests == []


def test_conversion_of_neutral_messages(settings):
    items = to_openai_input([
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [{"type": "text", "text": "kigger"},
                                          {"type": "tool_use", "id": "t1", "name": "run_sql", "input": {"sql": "æ"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    ])
    assert items == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "kigger"},
        {"type": "function_call", "call_id": "t1", "name": "run_sql", "arguments": '{"sql": "æ"}'},
        {"type": "function_call_output", "call_id": "t1", "output": "ok"},
    ]
    names = [t["name"] for t in to_openai_tools(tool_definitions(build_registry(settings)))]
    assert names == ["run_sql", "analyze_data", "run_ml", "create_chart", "show_table"]


def test_provider_selection(settings):
    settings.assistant_test_mode = False
    assert isinstance(create_llm(settings), OpenAILLM)  # standard
    settings.ai_provider = "anthropic"
    assert isinstance(create_llm(settings), AnthropicLLM)


def test_default_settings_use_openai():
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.ai_provider == "openai" and s.openai_model == "gpt-6.1-sol"
    assert s.openai_reasoning_effort == "medium" and s.llm_model == "gpt-6.1-sol"


def test_env_example_parses(tmp_path, monkeypatch):
    from app.config import BACKEND_DIR, Settings

    for var in ("AI_PROVIDER", "OPENAI_MODEL", "OPENAI_REASONING_EFFORT", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=BACKEND_DIR.parent / ".env.example")
    assert s.ai_provider == "openai" and s.openai_model == "gpt-6.1-sol" and s.openai_api_key == ""


def test_health_reports_provider_without_leaking_key(settings, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings.assistant_test_mode = False
    with TestClient(create_app(settings)) as c:
        h = c.get("/api/health").json()
        assert h["provider"] == "openai" and h["model"] == "gpt-6.1-sol" and h["llm_configured"] is False
    settings.openai_api_key = TEST_KEY
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/health")
        assert r.json()["llm_configured"] is True
        assert TEST_KEY not in r.text
        assert TEST_KEY not in c.get("/api/datasets").text


@pytest.fixture
def anyio_backend():
    return "asyncio"
