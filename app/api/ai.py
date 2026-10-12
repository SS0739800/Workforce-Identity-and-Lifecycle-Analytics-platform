"""AI endpoints. Each one computes facts with approved SQL first; Groq only explains them.

They are POST requests because each one records a row in ai_insight_runs.
"""

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.fallback import AIClient
from app.api.deps import get_ai_client
from app.db.database import get_session
from app.models import AIInsightRun
from app.schemas.ai import AIRunOut, FailureQuestionRequest, InsightResponse, QuestionRequest
from app.services import ai_service

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _respond(session: Session, result: ai_service.InsightResult) -> InsightResponse:
    session.commit()
    return InsightResponse(**result.__dict__)


@router.post("/ask", response_model=InsightResponse)
def ask(body: QuestionRequest, session: Session = Depends(get_session),
        client: AIClient | None = Depends(get_ai_client)):
    """Answer an analytics question by mapping it to an approved query, then explaining the result."""
    return _respond(session, ai_service.ask(session, client, body.question))


@router.post("/failure-explanation", response_model=InsightResponse)
def failure_explanation(body: FailureQuestionRequest, session: Session = Depends(get_session),
                        client: AIClient | None = Depends(get_ai_client)):
    return _respond(session, ai_service.explain_failures(session, client, body.question))


@router.post("/executive-summary", response_model=InsightResponse)
def executive_summary(
    month: str = Query(..., description="Month as YYYY-MM", examples=["2026-09"]),
    session: Session = Depends(get_session),
    client: AIClient | None = Depends(get_ai_client),
):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    year, number = map(int, month.split("-"))
    return _respond(session, ai_service.executive_summary(session, client, date(year, number, 1)))


@router.post("/data-quality-explanation", response_model=InsightResponse)
def data_quality_explanation(session: Session = Depends(get_session),
                             client: AIClient | None = Depends(get_ai_client)):
    return _respond(session, ai_service.explain_data_quality(session, client))


@router.post("/incident-report/{workflow_run_id}", response_model=InsightResponse)
def incident_report(workflow_run_id: int, session: Session = Depends(get_session),
                    client: AIClient | None = Depends(get_ai_client)):
    """Incident write-up for a failed workflow: observed facts, then possible areas to investigate."""
    return _respond(session, ai_service.incident_report(session, client, workflow_run_id))


@router.get("/runs", response_model=list[AIRunOut])
def list_runs(limit: int = Query(20, ge=1, le=200), session: Session = Depends(get_session)):
    """Recent AI requests, for monitoring. Contains summaries only, never full prompts."""
    return session.scalars(select(AIInsightRun).order_by(AIInsightRun.id.desc()).limit(limit)).all()
