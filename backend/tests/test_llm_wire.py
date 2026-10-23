"""Tester AnthropicLLM mod en lokal fake Messages-API: request-format og parsing af stream med tool_use."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.agent.llm import AnthropicLLM

EVENTS = [
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Jeg "}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "kigger."}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
        "type": "tool_use", "id": "toolu_1", "name": "run_sql", "input": {}}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {
        "type": "input_json_delta", "partial_json": "{\"sql\": \"SELECT 1 FROM meal_events\", \"title\": \"t\"}"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                       "usage": {"output_tokens": 20}}),
    ("message_stop", {"type": "message_stop"}),
]


class FakeApi(BaseHTTPRequestHandler):
    captured: dict = {}

    def do_POST(self):
        body = self.rfile.read(int(self.headers["content-length"]))
        FakeApi.captured = {"path": self.path, "headers": dict(self.headers), "body": json.loads(body)}
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for name, data in EVENTS:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_api():
    server = HTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.mark.anyio
async def test_stream_turn_parses_text_and_tool_use(fake_api, settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", fake_api)
    settings.anthropic_api_key = "test-key"
    llm = AnthropicLLM(settings)
    texts = []

    async def on_text(t):
        texts.append(t)

    tools = [{"name": "run_sql", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    turn = await llm.turn(system="sys", tools=tools, messages=[{"role": "user", "content": "q"}], on_text=on_text)

    assert "".join(texts) == "Jeg kigger."
    assert turn.stop_reason == "tool_use"
    assert turn.tool_uses[0].name == "run_sql"
    assert turn.tool_uses[0].input == {"sql": "SELECT 1 FROM meal_events", "title": "t"}

    req = FakeApi.captured
    body = req["body"]
    assert req["path"].startswith("/v1/messages")
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["output_config"] == {"effort": "medium"}
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in req["headers"]["anthropic-beta"]
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["eager_input_streaming"] is True
    assert "thinking" not in body and "temperature" not in body


@pytest.fixture
def anyio_backend():
    return "asyncio"
