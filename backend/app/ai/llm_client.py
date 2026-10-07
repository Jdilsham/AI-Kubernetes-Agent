import time

import httpx
from loguru import logger

from app.core.config import get_settings


class LLMError(Exception):
    """Raised when the LLM cannot be reached or returns an unusable answer."""


def chat_completion(messages: list[dict[str, str]]) -> str:
    """Call OpenRouter and return the assistant message text (with retries)."""
    settings = get_settings()
    if not settings.openrouter_api_key or not settings.openrouter_model:
        raise LLMError("AI is not configured.\n\nSet the LLM API key and model (Helm: llm.apiKey and llm.model, or OPENROUTER_API_KEY / OPENROUTER_MODEL).")

    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    body = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    last_error = "unknown error"
    for attempt in range(1, settings.llm_max_retries + 2):
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=settings.llm_timeout_seconds)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"  # retryable
            elif resp.status_code in (401, 403):
                raise LLMError("OpenRouter rejected the API key.\n\nPlease check the LLM API key (llm.apiKey).")
            elif resp.status_code >= 400:
                raise LLMError(
                    f"OpenRouter rejected the request (HTTP {resp.status_code}).\n\nPlease check the LLM model name (llm.model)."
                )
            else:
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = type(exc).__name__
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError("Unexpected response format from OpenRouter") from exc

        logger.warning("LLM call attempt {} failed: {}", attempt, last_error)
        time.sleep(2 ** (attempt - 1))

    if "Timeout" in last_error:
        raise LLMError("The AI model took too long to respond. Please try again.")
    if last_error == "HTTP 429":
        raise LLMError("The AI model is busy or rate-limited right now. Please try again in a minute.")
    raise LLMError(f"The AI service is unavailable right now ({last_error}). Please try again later.")
