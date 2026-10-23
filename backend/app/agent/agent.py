"""Agent-loop: AI-modellen vælger værktøjer, backend kører dem, og hvert trin streames som events til frontend."""

import asyncio
import re
from dataclasses import dataclass
from typing import AsyncIterator, Literal

from pydantic import BaseModel, Field

from app.agent.llm import LLM, LLMError
from app.agent.router import plan_question
from app.config import Settings
from app.data.sources import DataSource
from app.tools.ml import MLFunction
from app.tools.registry import ToolExecutor

MAX_TOOL_CONTENT = 30_000
DATA_TOOLS = {"run_sql", "analyze_data", "run_ml"}
UNGROUNDED_NOTICE = ("Svaret indeholder tal, men der blev ikke hentet eller beregnet data til dette svar. "
                     "Tallene kan stamme fra tidligere svar i samtalen - kontrollér dem, før du bruger dem.")


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=12_000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=40)


@dataclass
class AgentDeps:
    settings: Settings
    source: DataSource
    ml_registry: dict[str, MLFunction]
    llm: LLM
    system_prompt: str
    tools: list[dict]


def _history_messages(history: list[HistoryMessage]) -> list[dict]:
    """Kun afsluttede tekst-ture; sikrer at historikken starter med user og veksler korrekt."""
    msgs: list[dict] = []
    for h in history[-20:]:
        if not h.content.strip():
            continue
        if msgs and msgs[-1]["role"] == h.role:
            msgs[-1]["content"] += "\n\n" + h.content
        else:
            msgs.append({"role": h.role, "content": h.content})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] == "user":
        msgs.pop()
    return msgs


async def run_agent(request: ChatRequest, deps: AgentDeps) -> AsyncIterator[dict]:
    executor = ToolExecutor(deps.settings, deps.source, deps.ml_registry)
    plan = plan_question(request.message, list(deps.ml_registry))
    # Hintet sendes kun til modellen i denne tur; brugerens egen tekst gemmes uændret i historikken.
    content = f"{request.message}\n\n{plan.hint()}" if plan.has_hint else request.message
    messages = _history_messages(request.history) + [{"role": "user", "content": content}]
    yield {"type": "start", "demo": deps.source.is_demo, "data_source": deps.source.kind}
    yield plan.event()
    answer: list[str] = []
    grounded_steps = 0

    for _ in range(deps.settings.agent_max_steps):
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def on_text(text: str) -> None:
            answer.append(text)
            await queue.put({"type": "text_delta", "text": text})

        task = asyncio.create_task(deps.llm.turn(system=deps.system_prompt, tools=deps.tools,
                                                 messages=messages, on_text=on_text))
        try:
            while not (task.done() and queue.empty()):
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
            turn = task.result()
        except LLMError as e:
            yield {"type": "error", "message": str(e)}
            return
        finally:
            if not task.done():
                task.cancel()

        messages.append({"role": "assistant", "content": turn.content})

        if turn.stop_reason == "refusal":
            yield {"type": "error", "message": "AI-modellen afviste at besvare denne forespørgsel."}
            return
        if turn.stop_reason == "pause_turn":
            continue
        if turn.stop_reason == "max_tokens":
            yield {"type": "error", "message": "Svaret blev for langt. Prøv at afgrænse spørgsmålet."}
            return
        if not turn.tool_uses:
            if grounded_steps == 0 and re.search(r"\d", "".join(answer)):
                yield {"type": "notice", "level": "warning", "message": UNGROUNDED_NOTICE}
            yield {"type": "done"}
            return

        tool_results = []
        for tu in turn.tool_uses:
            yield {"type": "step", "id": tu.id, "tool": tu.name, "input": tu.input}
            outcome = await asyncio.to_thread(executor.execute, tu.name, tu.input)
            for event in outcome.events:
                yield {**event, "step_id": tu.id}
            yield {"type": "step_done", "id": tu.id, "ok": not outcome.is_error, "summary": outcome.summary}
            if tu.name in DATA_TOOLS and not outcome.is_error:
                grounded_steps += 1
            result = {"type": "tool_result", "tool_use_id": tu.id, "content": outcome.content[:MAX_TOOL_CONTENT]}
            if outcome.is_error:
                result["is_error"] = True
            tool_results.append(result)
        messages.append({"role": "user", "content": tool_results})
        yield {"type": "text_break"}

    yield {"type": "error", "message": "Analysen nåede det maksimale antal trin. Prøv et mere afgrænset spørgsmål."}
