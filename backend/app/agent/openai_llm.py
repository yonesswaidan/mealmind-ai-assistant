"""OpenAI-provider via Responses API: streaming, function calling og stateless samtaler.

Samtalen sendes i sin helhed hver tur (store=False), så OpenAI ikke gemmer data mellem kald. Reasoning-items
returneres krypteret og sendes med tilbage, så modellen bevarer sin tankegang mellem værktøjskald.
"""

import json
import logging

import openai

from app.agent.llm import LLMError, TextCallback, ToolUse, Turn, openai_credentials_available
from app.config import Settings

log = logging.getLogger("assistant")

MAX_OUTPUT_TOKENS = 32_000


def to_openai_tools(tools: list[dict]) -> list[dict]:
    """Agentens tool-definitioner (name/description/input_schema) som Responses API function tools."""
    return [{"type": "function", "name": t["name"], "description": t["description"],
             "parameters": t["input_schema"], "strict": False} for t in tools]


def to_openai_input(messages: list[dict]) -> list[dict]:
    """Provider-neutrale beskeder → Responses API input-items."""
    items: list[dict] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            items.append({"role": m["role"], "content": content})
            continue
        for block in content:
            kind = block.get("type")
            if kind == "text":
                items.append({"role": m["role"], "content": block["text"]})
            elif kind == "tool_use":
                items.append({"type": "function_call", "call_id": block["id"], "name": block["name"],
                              "arguments": json.dumps(block["input"], ensure_ascii=False)})
            elif kind == "tool_result":
                output = block["content"]
                if block.get("is_error"):
                    output = f"FEJL: {output}"
                items.append({"type": "function_call_output", "call_id": block["tool_use_id"], "output": output})
            else:
                # Output-item fra en tidligere OpenAI-tur (reasoning, message, function_call) sendes uændret retur.
                items.append(block)
    return items


def parse_response(response) -> Turn:
    tool_uses: list[ToolUse] = []
    refused = False
    for item in response.output:
        if item.type == "function_call":
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = item.arguments  # executor afviser ikke-objekter, og modellen får fejlen at rette ud fra
            tool_uses.append(ToolUse(item.call_id, item.name, args))
        elif item.type == "message":
            refused = refused or any(c.type == "refusal" for c in item.content)

    reason = response.incomplete_details.reason if response.incomplete_details else None
    if refused or reason == "content_filter":
        stop_reason = "refusal"
    elif reason == "max_output_tokens":
        stop_reason = "max_tokens"
    elif tool_uses:
        stop_reason = "tool_use"
    else:
        stop_reason = "end_turn"
    return Turn(content=[item.to_dict() for item in response.output], stop_reason=stop_reason, tool_uses=tool_uses)


def _stream_error(code: str | None, message: str | None) -> LLMError:
    if code == "insufficient_quota":
        return LLMError("OpenAI-kontoen har ikke mere kredit. Tjek billing på platform.openai.com.")
    if code == "rate_limit_exceeded":
        return LLMError("AI-tjenesten er midlertidigt overbelastet (rate limit). Prøv igen om lidt.")
    log.warning("OpenAI-stream fejlede: %s %s", code, message)
    return LLMError("AI-tjenesten kunne ikke fuldføre svaret. Prøv igen.")


class OpenAILLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.openai_model
        self.effort = settings.openai_reasoning_effort
        self._client: openai.AsyncOpenAI | None = None

    @property
    def client(self) -> openai.AsyncOpenAI:
        # Oprettes først ved brug: SDK'en fejler ved oprettelse, hvis der ikke findes en nøgle.
        if self._client is None:
            self._client = openai.AsyncOpenAI(api_key=self.settings.openai_api_key or None,
                                              max_retries=3, timeout=300.0)
        return self._client

    async def turn(self, *, system: str, tools: list[dict], messages: list[dict], on_text: TextCallback) -> Turn:
        if not openai_credentials_available(self.settings):
            raise LLMError("AI-modellen er ikke konfigureret. Sæt OPENAI_API_KEY i .env og genstart backend.")
        response = None
        try:
            stream = await self.client.responses.create(
                model=self.model,
                instructions=system,
                input=to_openai_input(messages),
                tools=to_openai_tools(tools),
                reasoning={"effort": self.effort},
                max_output_tokens=MAX_OUTPUT_TOKENS,
                store=False,
                include=["reasoning.encrypted_content"],
                stream=True,
            )
            async with stream:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        await on_text(event.delta)
                    elif event.type in ("response.completed", "response.incomplete"):
                        response = event.response
                    elif event.type == "response.failed":
                        error = event.response.error
                        raise _stream_error(error.code if error else None, error.message if error else None)
                    elif event.type == "error":
                        raise _stream_error(event.code, event.message)
        except openai.AuthenticationError as e:
            raise LLMError("OpenAI API-nøglen er ugyldig. Tjek OPENAI_API_KEY i .env.") from e
        except openai.PermissionDeniedError as e:
            raise LLMError(f"API-nøglen har ikke adgang til modellen '{self.model}'.") from e
        except (openai.NotFoundError, openai.BadRequestError) as e:
            if isinstance(e, openai.NotFoundError) or e.code == "model_not_found":
                raise LLMError(f"Modellen '{self.model}' findes ikke eller er ikke tilgængelig for din "
                               "OpenAI-konto. Tjek OPENAI_MODEL i .env.") from e
            log.warning("OpenAI afviste forespørgslen: %s", e.message)
            raise LLMError(f"AI-tjenesten afviste forespørgslen: {e.message[:300]}") from e
        except openai.RateLimitError as e:
            raise _stream_error(e.code or "rate_limit_exceeded", None) from e
        except openai.APIConnectionError as e:
            raise LLMError("Kunne ikke forbinde til AI-tjenesten. Tjek netværket.") from e
        except openai.APIStatusError as e:
            raise LLMError(f"AI-tjenesten svarede med fejl ({e.status_code}).") from e
        except openai.APIError as e:
            # Fejl sendt midt i streamen som {"error": {...}}.
            raise _stream_error(e.code, e.message) from e

        if response is None:
            raise LLMError("Forbindelsen til AI-tjenesten blev afbrudt. Prøv igen.")
        return parse_response(response)
