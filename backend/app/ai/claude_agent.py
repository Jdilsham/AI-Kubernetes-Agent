"""Claude investigates the cluster in a loop: reason, run a read-only kubectl command, read the output, repeat.

The model ends by calling `submit_diagnosis`, which returns the same issue structure the single-shot path
produces, so everything downstream (fix guards, storage, UI) is shared."""

import time
from collections.abc import Callable
from typing import Any

import anthropic
from loguru import logger

from app.ai.agent_common import EXTRA_TURNS, TOOLS, first_message, label
from app.ai.agent_tools import run_command
from app.ai.llm_client import LLMError
from app.ai.prompt_builder import AGENT_SYSTEM_PROMPT
from app.core.config import get_settings

MAX_TOKENS = 16000
REQUEST_TIMEOUT = 120.0


def _llm_error(exc: anthropic.APIError) -> LLMError:
    """Friendly messages for the failures a user can act on."""
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMError("Claude rejected the API key.\n\nPlease check ANTHROPIC_API_KEY (Helm: llm.apiKey).")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return LLMError("The Claude API key is not allowed to use this model.\n\nCheck the model name (ANTHROPIC_MODEL) and your Anthropic account.")
    if isinstance(exc, anthropic.NotFoundError):
        return LLMError("Claude model not found.\n\nPlease check the model name (ANTHROPIC_MODEL, Helm: llm.model).")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("Claude is rate-limited right now. Please try again in a minute.")
    if isinstance(exc, anthropic.APITimeoutError):
        return LLMError("Claude took too long to respond. Please try again.")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("Could not reach the Claude API.\n\nCheck the network access of the backend (api.anthropic.com).")
    if isinstance(exc, anthropic.BadRequestError):
        # e.g. "Your credit balance is too low" - the message says what to do
        return LLMError(f"Claude rejected the request: {exc.message}")
    return LLMError(f"The Claude API returned an error ({getattr(exc, 'status_code', 'unknown')}). Please try again later.")


def run_agent(investigation: dict[str, Any], on_step: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Investigate with Claude and return the arguments of its `submit_diagnosis` call."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=REQUEST_TIMEOUT, max_retries=2)
    deadline = time.monotonic() + settings.agent_timeout_seconds

    def step(text: str) -> None:
        if on_step:
            on_step(f"ai|{text}")

    messages: list[dict[str, Any]] = [{"role": "user", "content": first_message(investigation)}]
    commands_run = 0
    nudged = False
    usage = {"input": 0, "output": 0, "cache_read": 0}

    step("Reviewing the first-look results")
    for _ in range(settings.agent_max_steps + EXTRA_TURNS):
        if time.monotonic() > deadline:
            raise LLMError("The investigation took too long. Please try again, or lower AGENT_MAX_STEPS.")
        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=MAX_TOKENS,
                system=AGENT_SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": settings.agent_effort},
                cache_control={"type": "ephemeral"},  # the history grows every step; cache the part already paid for
            )
        except anthropic.APIError as exc:
            logger.error("Claude API error: {}", exc)
            raise _llm_error(exc) from exc

        usage["input"] += response.usage.input_tokens
        usage["output"] += response.usage.output_tokens
        usage["cache_read"] += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        if response.stop_reason == "refusal":
            raise LLMError("The AI declined to analyze this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The AI ran out of space while answering. Please try again.")

        messages.append({"role": "assistant", "content": response.content})
        tool_uses = [b for b in response.content if b.type == "tool_use"]

        submitted = next((b for b in tool_uses if b.name == "submit_diagnosis"), None)
        if submitted:
            logger.info("Agent finished after {} kubectl command(s); tokens {}", commands_run, usage)
            return dict(submitted.input)

        if not tool_uses:  # answered in prose without submitting: ask once for the structured answer
            if nudged:
                raise LLMError("The AI did not return a usable diagnosis. Please try again.")
            nudged = True
            messages.append({"role": "user", "content": "Call submit_diagnosis now with your final diagnosis."})
            continue

        results: list[dict[str, Any]] = []
        for use in tool_uses:
            command = str(use.input.get("command", "")) if use.name == "kubectl" else ""
            if use.name != "kubectl":
                text, is_error = f"Unknown tool '{use.name}'.", True
            elif commands_run >= settings.agent_max_steps:
                text, is_error = "Command budget used up. Call submit_diagnosis now with what you found.", True
            else:
                commands_run += 1
                step(f"kubectl {label(command)}")
                text, is_error = run_command(command)
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": text, "is_error": is_error})
        if commands_run >= settings.agent_max_steps:
            results.append({"type": "text", "text": "You have used all your kubectl commands. Call submit_diagnosis now."})
        step("Writing the final diagnosis" if commands_run >= settings.agent_max_steps else "Thinking about the results")
        messages.append({"role": "user", "content": results})

    raise LLMError("The AI did not finish the investigation. Please try again.")
