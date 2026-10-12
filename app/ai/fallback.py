"""Try one AI provider, then another.

Groq is the primary provider and Gemini the fallback. If Groq can't answer (rate limit or
quota exhausted, timeout, outage, error), the same request goes to Gemini. The response
records which model answered, so the fallback shows up in ai_insight_runs.
"""

import logging
from typing import Protocol

from app.ai.client import AIError, AIResponse

logger = logging.getLogger(__name__)


class AIClient(Protocol):
    model: str

    def complete(self, system: str, user: str, json_output: bool = False) -> AIResponse: ...


class FallbackClient:
    def __init__(self, primary: AIClient, fallback: AIClient):
        self.primary = primary
        self.fallback = fallback
        self.model = primary.model

    def complete(self, system: str, user: str, json_output: bool = False) -> AIResponse:
        try:
            return self.primary.complete(system, user, json_output)
        except AIError as error:
            logger.warning("Primary AI model %s failed (%s); trying %s", self.primary.model, error.status,
                           self.fallback.model)
        # If the fallback fails too, its error is what the caller sees and logs.
        return self.fallback.complete(system, user, json_output)
