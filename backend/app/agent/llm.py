import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

import anthropic

from app.config import Settings

TextCallback = Callable[[str], Awaitable[None]]


@dataclass
class ToolUse:
    id: str
    name: str
    input: Any


@dataclass
class Turn:
    content: list
    stop_reason: str
    tool_uses: list[ToolUse]


class LLMError(RuntimeError):
    """Fejl der kan vises direkte til brugeren."""


class LLM(Protocol):
    """Fælles interface for AI-providers.

    `messages` bruger et provider-neutralt format: user/assistant med tekst, assistant-blokke af typen
    "text"/"tool_use" og user-blokke af typen "tool_result". Hver provider oversætter selv til sit API-format.
    """

    async def turn(self, *, system: str, tools: list[dict], messages: list[dict], on_text: TextCallback) -> Turn: ...


def anthropic_credentials_available(settings: Settings) -> bool:
    if settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


def openai_credentials_available(settings: Settings) -> bool:
    return bool(settings.openai_api_key or os.environ.get("OPENAI_API_KEY"))


def credentials_available(settings: Settings) -> bool:
    if settings.ai_provider == "openai":
        return openai_credentials_available(settings)
    return anthropic_credentials_available(settings)


def create_llm(settings: Settings) -> LLM:
    if settings.ai_provider == "openai":
        from app.agent.openai_llm import OpenAILLM

        return OpenAILLM(settings)
    return AnthropicLLM(settings)


class AnthropicLLM:
    def __init__(self, settings: Settings):
        kwargs = {"api_key": settings.anthropic_api_key} if settings.anthropic_api_key else {}
        self.client = anthropic.AsyncAnthropic(max_retries=3, timeout=300.0, **kwargs)
        self.settings = settings
        self.model = settings.anthropic_model
        self.effort = settings.anthropic_effort

    async def turn(self, *, system: str, tools: list[dict], messages: list[dict], on_text: TextCallback) -> Turn:
        if not anthropic_credentials_available(self.settings):
            raise LLMError("AI-modellen er ikke konfigureret. Sæt ANTHROPIC_API_KEY i .env og genstart backend.")
        streamed_tools = [{**t, "eager_input_streaming": True} for t in tools]
        for attempt in range(3):
            try:
                async with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=32000,
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    tools=streamed_tools,
                    messages=messages,
                    output_config={"effort": self.effort},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                ) as stream:
                    async for event in stream:
                        if event.type == "text":
                            await on_text(event.text)
                    message = await stream.get_final_message()
                break
            except ValueError:
                # Tool-input som SDK'en ikke kunne parse; turen sendes igen (begrænset antal gange).
                if attempt == 2:
                    raise LLMError("AI-modellen returnerede ugyldigt værktøjsinput. Prøv igen.")
            except anthropic.AuthenticationError as e:
                raise LLMError("Anthropic API-nøglen er ugyldig. Tjek ANTHROPIC_API_KEY i .env.") from e
            except anthropic.PermissionDeniedError as e:
                raise LLMError("API-nøglen har ikke adgang til den valgte model.") from e
            except anthropic.RateLimitError as e:
                raise LLMError("AI-tjenesten er midlertidigt overbelastet (rate limit). Prøv igen om lidt.") from e
            except anthropic.APIConnectionError as e:
                raise LLMError("Kunne ikke forbinde til AI-tjenesten. Tjek netværket.") from e
            except anthropic.APIStatusError as e:
                raise LLMError(f"AI-tjenesten svarede med fejl ({e.status_code}).") from e

        tool_uses = [ToolUse(b.id, b.name, b.input) for b in message.content if b.type == "tool_use"]
        return Turn(content=message.content, stop_reason=message.stop_reason or "end_turn", tool_uses=tool_uses)
