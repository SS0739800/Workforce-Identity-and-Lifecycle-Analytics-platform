"""Request dependencies for the operations endpoints. Tests override these to control time and failures."""

import random
from datetime import datetime, timezone
from functools import lru_cache

from app.ai.client import GroqClient
from app.ai.fallback import AIClient, FallbackClient
from app.ai.gemini_client import GeminiClient
from app.core.config import get_settings


@lru_cache
def get_ai_client() -> AIClient | None:
    """Groq, with Gemini as a fallback when both are configured.

    Returns None when neither API key is set; the AI endpoints then return data only.
    """
    settings = get_settings()
    groq_client = GroqClient.from_settings(settings)
    gemini_client = GeminiClient.from_settings(settings)
    if groq_client and gemini_client:
        return FallbackClient(groq_client, gemini_client)
    return groq_client or gemini_client


def get_now() -> datetime:
    return datetime.now(timezone.utc)


def get_rng() -> random.Random:
    # Unseeded: live runs fail at the documented rates, not in a fixed pattern.
    return random.Random()
