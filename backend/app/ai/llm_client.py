import json
import time
from typing import Any

import httpx
from loguru import logger

from app.core.config import get_settings


class LLMError(Exception):
    """Raised when the LLM cannot be reached or returns an unusable answer."""


def _post(url: str, body: dict, headers: dict, timeout: int) -> tuple[int, bytes]:
    """POST and read the whole response within a total deadline.

    OpenRouter sends the 200 header at once, then whitespace keepalives until the model answers. httpx's
    timeout is per read, so keepalives would reset it forever; enforce a wall-clock limit ourselves."""
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    with httpx.stream("POST", url, json=body, headers=headers, timeout=httpx.Timeout(30, read=30)) as resp:
        for chunk in resp.iter_bytes():
            chunks.append(chunk)
            if time.monotonic() > deadline:
                raise httpx.ReadTimeout("LLM response exceeded the total time limit")
        return resp.status_code, b"".join(chunks)


def post_chat(body: dict[str, Any]) -> dict[str, Any]:
    """POST a chat-completions request to the OpenAI-compatible provider and return the parsed response (with retries)."""
    settings = get_settings()
    if not settings.openrouter_api_key or not settings.openrouter_model:
        raise LLMError("AI is not configured.\n\nSet the LLM API key and model (Helm: llm.apiKey and llm.model, or OPENROUTER_API_KEY / OPENROUTER_MODEL).")

    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    body = {"model": settings.openrouter_model, **body}

    last_error = "unknown error"
    for attempt in range(1, settings.llm_max_retries + 2):
        try:
            status, raw = _post(url, body, headers, settings.llm_timeout_seconds)
            if status == 429 or status >= 500:
                last_error = f"HTTP {status}"  # retryable
            elif status in (401, 403):
                raise LLMError("OpenRouter rejected the API key.\n\nPlease check the LLM API key (llm.apiKey).")
            elif status >= 400:
                raise LLMError(f"OpenRouter rejected the request (HTTP {status}).\n\nPlease check the LLM model name (llm.model).")
            else:
                return json.loads(raw)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = type(exc).__name__
        except ValueError as exc:
            raise LLMError("Unexpected response format from OpenRouter") from exc

        logger.warning("LLM call attempt {} failed: {}", attempt, last_error)
        time.sleep(2 ** (attempt - 1))

    if "Timeout" in last_error:
        raise LLMError("The AI model took too long to respond. Please try again.")
    if last_error == "HTTP 429":
        raise LLMError("The AI model is busy or rate-limited right now. Please try again in a minute.")
    raise LLMError(f"The AI service is unavailable right now ({last_error}). Please try again later.")


def chat_completion(messages: list[dict[str, str]]) -> str:
    """Call the provider and return the assistant message text."""
    data = post_chat({"messages": messages, "temperature": 0, "response_format": {"type": "json_object"}})
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("Unexpected response format from OpenRouter") from exc
