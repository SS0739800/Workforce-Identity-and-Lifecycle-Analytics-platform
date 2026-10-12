"""Thin wrapper around the Groq SDK.

Every failure is turned into one of a few AIError types so callers can degrade
gracefully (return the computed data without an explanation) instead of failing.
"""

import logging
from dataclasses import dataclass

import groq

from app.core.config import Settings

logger = logging.getLogger(__name__)


class AIError(Exception):
    """Base class. `status` is what gets reported to the caller and logged."""

    status = "error"


class AIUnavailable(AIError):
    status = "unavailable"


class AIRateLimited(AIError):
    status = "rate_limited"


class AITimeout(AIError):
    status = "timeout"


class AIInvalidResponse(AIError):
    status = "invalid_response"


@dataclass(frozen=True)
class AIResponse:
    text: str
    model: str


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout: float, max_retries: int, max_completion_tokens: int):
        # The SDK retries rate limits and connection errors itself, with backoff.
        self._client = groq.Groq(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model = model
        self.max_completion_tokens = max_completion_tokens

    @classmethod
    def from_settings(cls, settings: Settings) -> "GroqClient | None":
        if not settings.groq_api_key:
            return None
        return cls(
            settings.groq_api_key,
            settings.groq_model,
            settings.groq_timeout_seconds,
            settings.groq_max_retries,
            settings.groq_max_completion_tokens,
        )

    def complete(self, system: str, user: str, json_output: bool = False) -> AIResponse:
        kwargs = {}
        if json_output:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.2,
                max_completion_tokens=self.max_completion_tokens,
                **kwargs,
            )
        except groq.RateLimitError as error:
            raise AIRateLimited("Groq rate limit reached; try again shortly") from error
        except groq.APITimeoutError as error:
            raise AITimeout("Groq did not respond in time") from error
        except groq.AuthenticationError as error:
            raise AIUnavailable("Groq rejected the API key") from error
        except groq.APIConnectionError as error:
            raise AIUnavailable("Could not reach Groq") from error
        except groq.APIStatusError as error:
            # Unknown or retired model, bad request, server error.
            raise AIError(f"Groq returned HTTP {error.status_code}") from error

        if not response.choices:
            raise AIInvalidResponse("Groq returned no choices")
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise AIInvalidResponse("Groq returned an empty answer")
        return AIResponse(text=text, model=response.model or self.model)
