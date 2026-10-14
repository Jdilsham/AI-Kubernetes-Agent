"""The same investigation loop as claude_agent, for OpenAI-compatible providers (OpenRouter, Gemini, Ollama, vLLM, ...).

It uses function calling over /chat/completions. Models differ a lot in how well they call tools; the loop is
forgiving (a JSON answer in plain text is accepted, bad tool arguments are sent back as an error)."""

import json
import re
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from app.ai.agent_common import EXTRA_TURNS, TOOLS, first_message, label
from app.ai.agent_tools import run_command
from app.ai.llm_client import LLMError, post_chat
from app.ai.prompt_builder import AGENT_SYSTEM_PROMPT
from app.core.config import get_settings

UNUSABLE_RETRIES = 2
FUNCTIONS = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in TOOLS]


def _json_answer(content: str | None) -> dict[str, Any] | None:
    """Models sometimes answer with the diagnosis as JSON text instead of calling submit_diagnosis."""
    text = re.sub(r"^```(?:json)?|```$", "", (content or "").strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("issues"), list) else None


def _arguments(call: dict[str, Any]) -> dict[str, Any] | None:
    raw = (call.get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _next_message(body: dict[str, Any]) -> dict[str, Any]:
    """Ask the model for its next message. Free providers sometimes answer 200 with an error or an empty body: retry those."""
    reason = "empty reply"
    for attempt in range(1, UNUSABLE_RETRIES + 2):
        data = post_chat(body)
        try:
            message = data["choices"][0]["message"]
            if isinstance(message, dict):
                return message
        except (KeyError, IndexError, TypeError):
            pass
        error = data.get("error") if isinstance(data, dict) else None
        reason = str((error.get("message") if isinstance(error, dict) else error) or json.dumps(data, default=str)[:200])
        logger.warning("Unusable AI reply (attempt {}): {}", attempt, json.dumps(data, default=str)[:500])
        time.sleep(2 * attempt)
    raise LLMError(f"The AI provider returned an unusable reply: {reason[:200]}\n\nTry again, or pick another model (OPENROUTER_MODEL).")


def run_openai_agent(investigation: dict[str, Any], on_step: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Investigate with an OpenAI-compatible model and return the arguments of its `submit_diagnosis` call."""
    settings = get_settings()
    deadline = time.monotonic() + settings.agent_timeout_seconds

    def step(text: str) -> None:
        if on_step:
            on_step(f"ai|{text}")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": first_message(investigation)},
    ]
    commands_run = 0
    nudged = False

    step("Reviewing the first-look results")
    for _ in range(settings.agent_max_steps + EXTRA_TURNS):
        if time.monotonic() > deadline:
            raise LLMError("The investigation took too long. Please try again, or lower AGENT_MAX_STEPS.")
        message = _next_message({"messages": messages, "tools": FUNCTIONS, "tool_choice": "auto"})

        calls = message.get("tool_calls") or []
        # Keep only the standard fields: providers add extras (reasoning, refusal, ...) that others reject on replay.
        messages.append({"role": "assistant", "content": message.get("content") or "", **({"tool_calls": calls} if calls else {})})

        if not calls:  # answered in text: accept a JSON diagnosis, otherwise ask once for the structured answer
            answer = _json_answer(message.get("content"))
            if answer:
                return answer
            if nudged:
                raise LLMError("The AI did not return a usable diagnosis. Please try again.")
            nudged = True
            messages.append({"role": "user", "content": "Call submit_diagnosis now with your final diagnosis."})
            continue

        for call in calls:
            if (call.get("function") or {}).get("name") == "submit_diagnosis":
                args = _arguments(call)
                if args is not None and isinstance(args.get("issues"), list):
                    logger.info("Agent finished after {} kubectl command(s)", commands_run)
                    return args

        for call in calls:
            name = (call.get("function") or {}).get("name")
            args = _arguments(call)
            if args is None:
                text = "The arguments were not valid JSON. Call the tool again with a JSON object."
            elif name == "submit_diagnosis":
                text = "submit_diagnosis needs `summary` and an `issues` list. Call it again with both."
            elif name != "kubectl":
                text = f"Unknown tool '{name}'."
            elif commands_run >= settings.agent_max_steps:
                text = "Command budget used up. Call submit_diagnosis now with what you found."
            else:
                commands_run += 1
                command = str(args.get("command", ""))
                step(f"kubectl {label(command)}")
                text, _ = run_command(command)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": text})
        if commands_run >= settings.agent_max_steps:
            messages.append({"role": "user", "content": "You have used all your kubectl commands. Call submit_diagnosis now."})
        step("Writing the final diagnosis" if commands_run >= settings.agent_max_steps else "Thinking about the results")

    raise LLMError("The AI did not finish the investigation. Please try again.")
