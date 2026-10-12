"""Gemini client with the same interface and error types as the Groq client.

Used as a fallback when Groq can't answer (for example when its token quota runs out).
"""

import httpx
from google import genai
from google.genai import errors, types

from app.ai.client import AIError, AIInvalidResponse, AIRateLimited, AIResponse, AITimeout, AIUnavailable
from app.core.config import Settings


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: float, max_output_tokens: int):
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # milliseconds
        )
        self.model = model
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_settings(cls, settings: Settings) -> "GeminiClient | None":
        if not settings.gemini_api_key:
            return None
        return cls(settings.gemini_api_key, settings.gemini_model, settings.gemini_timeout_seconds,
                   settings.gemini_max_output_tokens)

    def complete(self, system: str, user: str, json_output: bool = False) -> AIResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            max_output_tokens=self.max_output_tokens,
            response_mime_type="application/json" if json_output else None,
        )
        try:
            response = self._client.models.generate_content(model=self.model, contents=user, config=config)
        except errors.ClientError as error:
            if error.code == 429:
                raise AIRateLimited("Gemini rate limit or quota reached") from error
            if error.code in (401, 403):
                raise AIUnavailable("Gemini rejected the API key") from error
            raise AIError(f"Gemini returned HTTP {error.code}") from error
        except errors.APIError as error:
            raise AIError(f"Gemini returned HTTP {error.code}") from error
        except httpx.TimeoutException as error:
            raise AITimeout("Gemini did not respond in time") from error
        except httpx.HTTPError as error:
            raise AIUnavailable("Could not reach Gemini") from error

        text = (response.text or "").strip()
        if not text:
            raise AIInvalidResponse("Gemini returned an empty answer")
        return AIResponse(text=text, model=self.model)
