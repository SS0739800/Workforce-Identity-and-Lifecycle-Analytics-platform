from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)


class FailureQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        "Why are license removal failures higher than group removal failures?", min_length=3, max_length=500
    )


class InsightResponse(BaseModel):
    """`facts` is what the database computed. `explanation` is Groq's text about those facts,
    or a plain template when Groq isn't available. Check `ai_status` before relying on it."""

    insight_type: str
    ai_status: str = Field(description="ok, needs_review, unavailable, rate_limited, timeout, invalid_response, "
                                       "error, unmatched or no_data")
    explanation: str | None
    facts: dict[str, Any]
    model: str | None
    ungrounded_numbers: list[str] = Field(description="Numbers in the explanation that are not in the facts")
    message: str | None
    run_id: int | None


class AIRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    insight_type: str
    requested_at: datetime
    input_summary: str | None
    output_summary: str | None
    model: str | None
    status: str
    error_message: str | None
