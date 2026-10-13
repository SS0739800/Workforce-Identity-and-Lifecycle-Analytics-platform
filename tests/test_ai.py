"""AI layer tests. Groq is never called: a fake client stands in for it."""

import json
from collections import Counter
from datetime import date

import groq
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.client import AIError, AIInvalidResponse, AIRateLimited, AIResponse, AITimeout, AIUnavailable, GroqClient
from app.ai.grounding import ungrounded_numbers
from app.ai.router import parse_period, route_by_keywords, route_with_ai, workflow_type_in
from app.ai.sanitize import contains_personal_data, sanitize
from app.api.deps import get_ai_client
from app.db.database import get_session
from app.main import app
from app.models import AIInsightRun, Employee, WorkflowRun
from app.services import ai_service
from app.services.workflow_service import WorkflowNotFound

AS_OF = date(2026, 9, 30)


class FakeClient:
    """Records every request and returns a canned answer (or raises a canned error)."""

    model = "fake-model"

    def __init__(self, answer: str = "Observed: see facts.", error: AIError | None = None, route: dict | None = None):
        self.answer, self.error, self.route = answer, error, route
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, json_output: bool = False) -> AIResponse:
        self.calls.append({"system": system, "user": user, "json_output": json_output})
        if self.error:
            raise self.error
        if json_output:
            return AIResponse(json.dumps(self.route), self.model)
        return AIResponse(self.answer, self.model)


# --- sanitizing ------------------------------------------------------------------------------

def test_sanitize_drops_personal_fields_and_redacts_emails():
    raw = {
        "employee_name": "Alex Smith",
        "rows": [{"email": "alex.smith@northstar-mfg.example", "department": "Sales", "hr_employee_id": "EMP00001"}],
        "note": "contact alex.smith@northstar-mfg.example",
    }
    clean = sanitize(raw)
    assert clean == {"rows": [{"department": "Sales", "hr_employee_id": "EMP00001"}], "note": "contact [redacted email]"}
    assert contains_personal_data(raw)
    assert not contains_personal_data(clean)


# --- grounding --------------------------------------------------------------------------------

def test_grounded_answer_passes_in_any_reasonable_format():
    facts = {"rate": 89.7, "share": 0.156, "count": 1010, "when": date(2026, 9, 30)}
    answer = "Success was 89.7% across 1,010 employees; failure rate 15.6%. Data to 30 September 2026. Top 3 items."
    assert ungrounded_numbers(answer, facts) == []


def test_invented_numbers_are_flagged():
    facts = {"failures": 79}
    assert ungrounded_numbers("There were 79 failures, up 23.5% on last month.", facts) == ["23.5"]


def test_numbers_in_fact_names_count_as_grounded():
    """Found by docs/ai-examples.md: the model quoted the window from a key name and was wrongly flagged."""
    facts = {"same_error_type_in_previous_30_days": 0}
    assert ungrounded_numbers("PERMISSION_ERROR occurrences in the previous 30 days: 0", facts) == []


# --- routing ------------------------------------------------------------------------------------

@pytest.mark.parametrize("question, query", [
    ("Which departments had the most synchronization failures this quarter?", "sync_failures_by_department"),
    ("What were the most common offboarding failures last month?", "workflow_action_failures"),
    ("Why do sync records fail?", "sync_failures_by_error_type"),
    ("Which licenses fail to be removed?", "license_cleanup_summary"),
    ("What are the most common data quality issues?", "dq_by_type"),
    ("How quickly are accounts disabled after termination?", "time_to_disable_account"),
    ("Do terminated employees still have access?", "access_remaining_after_offboarding"),
    ("How reliable is the sync?", "sync_summary"),
])
def test_keyword_routing(question, query):
    assert route_by_keywords(question).query == query


def test_unrelated_question_is_not_routed():
    assert route_by_keywords("Tell me a joke about printers") is None


@pytest.mark.parametrize("text, expected", [
    ("onboarding failures", "onboarding"),
    ("offboarding failures", "offboarding"),
    ("problems returning from leave", "return_from_leave"),
    ("failed leave workflows", "leave"),
])
def test_workflow_type_detection(text, expected):
    assert workflow_type_in(text) == expected


@pytest.mark.parametrize("phrase, start, end", [
    ("this quarter", date(2026, 7, 1), date(2026, 9, 30)),
    ("last quarter", date(2026, 4, 1), date(2026, 6, 30)),
    ("last month", date(2026, 8, 1), date(2026, 8, 31)),
    ("this year", date(2026, 1, 1), date(2026, 9, 30)),
    ("the last 30 days", date(2026, 9, 1), date(2026, 9, 30)),
    ("in March", date(2026, 3, 1), date(2026, 3, 31)),
    ("in November", date(2025, 11, 1), date(2025, 11, 30)),
    ("December 2025", date(2025, 12, 1), date(2025, 12, 31)),
    ("overall", None, None),
    ("what may cause this", None, None),
])
def test_time_phrases_are_parsed_in_code(phrase, start, end):
    period = parse_period(f"failures {phrase}", AS_OF)
    assert (period.start, period.end) == (start, end)


def test_ai_routing_only_accepts_approved_query_names():
    assert route_with_ai("anything", FakeClient(route={"query": "dq_summary"})).query == "dq_summary"
    assert route_with_ai("anything", FakeClient(route={"query": "drop_table_employees"})) is None
    assert route_with_ai("anything", FakeClient(route={"query": None})) is None
    assert route_with_ai("anything", FakeClient(error=AIRateLimited("slow down"))) is None
    routed = route_with_ai("x", FakeClient(route={"query": "workflow_action_failures", "workflow_type": "evil"}))
    assert routed.params == {"workflow_type": "offboarding"}


# --- insights -----------------------------------------------------------------------------------

def test_question_without_groq_still_returns_data(db):
    result = ai_service.ask(db, None, "Which departments had the most sync failures this quarter?", as_of=AS_OF)
    assert result.ai_status == "unavailable"
    assert result.explanation is None
    assert result.facts["query"] == "sync_failures_by_department"
    assert result.facts["period"]["start"] == date(2026, 7, 1)
    assert result.facts["row_count"] > 0


def test_question_with_groq_is_explained_and_logged(db):
    client = FakeClient(answer="Production had the most sync failures.")
    result = ai_service.ask(db, client, "Which departments had the most sync failures this quarter?", as_of=AS_OF)
    assert result.ai_status == "ok"
    assert result.explanation == "Production had the most sync failures."
    assert "FACTS" in client.calls[0]["user"] and "sync_failures_by_department" in client.calls[0]["user"]
    log = db.get(AIInsightRun, result.run_id)
    assert (log.insight_type, log.status, log.model) == ("question", "ok", "fake-model")
    assert "sync_failures_by_department" in log.input_summary


def test_answer_with_invented_number_needs_review(db):
    client = FakeClient(answer="Failures rose by 37.25% this quarter.")
    result = ai_service.ask(db, client, "Which departments had the most sync failures this quarter?", as_of=AS_OF)
    assert result.ai_status == "needs_review"
    assert result.ungrounded_numbers == ["37.25"]


@pytest.mark.parametrize("error, status", [
    (AIRateLimited("limit"), "rate_limited"),
    (AITimeout("slow"), "timeout"),
    (AIInvalidResponse("empty"), "invalid_response"),
    (AIError("HTTP 404"), "error"),
])
def test_groq_errors_degrade_to_data_only(db, error, status):
    result = ai_service.explain_failures(db, FakeClient(error=error), "Why do license removals fail more?")
    assert result.ai_status == status
    assert result.explanation is None
    assert result.facts["action_failure_rates"]
    assert db.get(AIInsightRun, result.run_id).error_message


def test_unmatched_and_empty_questions_do_not_call_groq(db):
    client = FakeClient()
    assert ai_service.ask(db, client, "Tell me a joke", as_of=AS_OF).ai_status == "unmatched"
    empty = ai_service.ask(db, client, "Which departments had sync failures in March 2020?", as_of=AS_OF)
    assert empty.ai_status == "no_data"
    assert [c for c in client.calls if not c["json_output"]] == []


def test_executive_summary_metrics_come_from_the_database(db, dataset):
    september = [r for r in dataset["workflow_runs"]
                 if r["workflow_type"] == "offboarding" and r["requested_at"].strftime("%Y-%m") == "2026-09"]
    runs = [r for r in dataset["sync_runs"] if r["started_at"].strftime("%Y-%m") == "2026-09"]
    result = ai_service.executive_summary(db, None, date(2026, 9, 1))
    assert result.facts["offboarding_workflows"] == len(september)
    assert result.facts["sync_runs"] == len(runs)
    assert result.explanation.startswith("Identity operations summary - September 2026")  # template fallback


def test_incident_report_sends_no_personal_data(db):
    run = db.scalars(select(WorkflowRun).where(WorkflowRun.status == "failed")).first()
    employee = db.get(Employee, run.employee_id)
    client = FakeClient(answer="Summary: workflow failed.")
    result = ai_service.incident_report(db, client, run.id)
    sent = client.calls[0]["user"]
    assert employee.first_name not in sent and employee.last_name not in sent
    assert employee.email not in sent and "@" not in sent
    assert employee.employee_id in sent
    assert result.facts["failed_actions"]


def test_incident_report_fallback_separates_observed_from_investigation(db):
    run = db.scalars(select(WorkflowRun).where(WorkflowRun.status == "failed")).first()
    result = ai_service.incident_report(db, None, run.id)
    text = result.explanation
    assert text.index("Observed") < text.index("Potential investigation areas (to check, not conclusions)")


def test_incident_report_only_for_failed_workflows(db):
    completed = db.scalars(select(WorkflowRun).where(WorkflowRun.status == "completed")).first()
    with pytest.raises(ai_service.IncidentNotApplicable):
        ai_service.incident_report(db, None, completed.id)
    with pytest.raises(WorkflowNotFound):
        ai_service.incident_report(db, None, 999_999)


def test_logged_runs_contain_no_personal_data(db):
    run = db.scalars(select(WorkflowRun).where(WorkflowRun.status == "failed")).first()
    ai_service.incident_report(db, FakeClient(answer="Summary."), run.id)
    for log in db.scalars(select(AIInsightRun)):
        assert not contains_personal_data({"input": log.input_summary or "", "output": log.output_summary or ""})


# --- Groq client error mapping ------------------------------------------------------------------

def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))


@pytest.mark.parametrize("raised, expected", [
    (groq.RateLimitError("limit", response=_response(429), body=None), AIRateLimited),
    (groq.APITimeoutError(request=httpx.Request("POST", "https://api.groq.com")), AITimeout),
    (groq.AuthenticationError("bad key", response=_response(401), body=None), AIUnavailable),
    (groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com")), AIUnavailable),
    (groq.NotFoundError("model not found", response=_response(404), body=None), AIError),
])
def test_client_maps_sdk_errors(monkeypatch, raised, expected):
    client = GroqClient("test-key", "some-model", timeout=1, max_retries=0, max_completion_tokens=100)

    def fail(**kwargs):
        raise raised

    monkeypatch.setattr(client._client.chat.completions, "create", fail)
    with pytest.raises(expected):
        client.complete("system", "user")


def test_client_rejects_empty_answers(monkeypatch):
    client = GroqClient("test-key", "some-model", timeout=1, max_retries=0, max_completion_tokens=100)
    empty = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "  "})()})()], "model": "m"})()
    monkeypatch.setattr(client._client.chat.completions, "create", lambda **kwargs: empty)
    with pytest.raises(AIInvalidResponse):
        client.complete("system", "user")


def test_no_api_key_means_no_client():
    from app.core.config import Settings

    assert GroqClient.from_settings(Settings(database_url="postgresql://x", groq_api_key=None)) is None


# --- API -----------------------------------------------------------------------------------------

@pytest.fixture
def api(db):
    fake = FakeClient(answer="Observed in the data.")
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_ai_client] = lambda: fake
    with TestClient(app) as client:
        yield client, fake
    app.dependency_overrides.clear()


def test_ask_endpoint(api):
    client, fake = api
    response = client.post("/api/ai/ask", json={"question": "What were the most common offboarding failures last month?"})
    assert response.status_code == 200
    body = response.json()
    assert body["ai_status"] == "ok"
    assert body["facts"]["query"] == "workflow_action_failures"
    assert body["facts"]["parameters"] == {"workflow_type": "offboarding"}


@pytest.mark.parametrize("payload", [{}, {"question": "a"}, {"question": "x" * 501}, {"question": "ok?", "sql": "DROP"}])
def test_ask_validates_input(api, payload):
    client, _ = api
    assert client.post("/api/ai/ask", json=payload).status_code == 422


def test_executive_summary_month_validation(api):
    client, _ = api
    assert client.post("/api/ai/executive-summary", params={"month": "September"}).status_code == 422
    assert client.post("/api/ai/executive-summary", params={"month": "2026-09"}).status_code == 200


def test_incident_endpoint_errors(api, db):
    client, _ = api
    completed = db.scalars(select(WorkflowRun).where(WorkflowRun.status == "completed")).first()
    assert client.post(f"/api/ai/incident-report/{completed.id}").status_code == 409
    assert client.post("/api/ai/incident-report/999999").status_code == 404


def test_runs_endpoint_lists_newest_first(api):
    client, _ = api
    client.post("/api/ai/data-quality-explanation")
    client.post("/api/ai/failure-explanation", json={})
    runs = client.get("/api/ai/runs", params={"limit": 2}).json()
    assert [r["insight_type"] for r in runs] == ["failure_explanation", "data_quality"]
    assert Counter(r["status"] for r in runs) == {"ok": 2}


# --- Gemini fallback ----------------------------------------------------------------------------

from google.genai import errors as genai_errors  # noqa: E402

from app.ai.fallback import FallbackClient  # noqa: E402
from app.ai.gemini_client import GeminiClient  # noqa: E402


class NamedFake(FakeClient):
    def __init__(self, model: str, **kwargs):
        super().__init__(**kwargs)
        self.model = model


def test_fallback_is_not_used_when_groq_answers():
    groq_fake, gemini_fake = NamedFake("groq", answer="from groq"), NamedFake("gemini", answer="from gemini")
    response = FallbackClient(groq_fake, gemini_fake).complete("s", "u")
    assert (response.text, response.model) == ("from groq", "groq")
    assert gemini_fake.calls == []


@pytest.mark.parametrize("error", [AIRateLimited("tokens used up"), AITimeout("slow"), AIUnavailable("down"), AIError("500")])
def test_gemini_answers_when_groq_cannot(error):
    groq_fake, gemini_fake = NamedFake("groq", error=error), NamedFake("gemini", answer="from gemini")
    response = FallbackClient(groq_fake, gemini_fake).complete("system", "user")
    assert (response.text, response.model) == ("from gemini", "gemini")
    assert gemini_fake.calls[0]["user"] == "user"


def test_when_both_fail_the_fallback_error_is_reported():
    client = FallbackClient(NamedFake("groq", error=AIRateLimited("groq")), NamedFake("gemini", error=AITimeout("gemini")))
    with pytest.raises(AITimeout):
        client.complete("s", "u")


def test_fallback_model_is_logged(db):
    client = FallbackClient(NamedFake("openai/gpt-oss-120b", error=AIRateLimited("quota")),
                            NamedFake("gemini-3.5-flash-lite", answer="Observed."))
    result = ai_service.explain_data_quality(db, client)
    assert result.ai_status == "ok"
    assert db.get(AIInsightRun, result.run_id).model == "gemini-3.5-flash-lite"


@pytest.mark.parametrize("raised, expected", [
    (genai_errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}), AIRateLimited),
    (genai_errors.ClientError(403, {"error": {"code": 403, "message": "key", "status": "PERMISSION_DENIED"}}), AIUnavailable),
    (genai_errors.ClientError(404, {"error": {"code": 404, "message": "no model", "status": "NOT_FOUND"}}), AIError),
    (genai_errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}), AIError),
    (httpx.ReadTimeout("slow"), AITimeout),
    (httpx.ConnectError("no network"), AIUnavailable),
])
def test_gemini_client_maps_sdk_errors(monkeypatch, raised, expected):
    client = GeminiClient("test-key", "gemini-3.5-flash-lite", timeout=1, max_output_tokens=100)

    def fail(**kwargs):
        raise raised

    monkeypatch.setattr(client._client.models, "generate_content", fail)
    with pytest.raises(expected):
        client.complete("system", "user")


def test_client_choice_follows_configured_keys(monkeypatch):
    from app.api import deps
    from app.core.config import Settings

    def client_for(**keys):
        deps.get_ai_client.cache_clear()
        monkeypatch.setattr(deps, "get_settings", lambda: Settings(database_url="postgresql://x", **keys))
        return deps.get_ai_client()

    assert client_for(groq_api_key=None, gemini_api_key=None) is None
    assert isinstance(client_for(groq_api_key="g", gemini_api_key=None), GroqClient)
    assert isinstance(client_for(groq_api_key=None, gemini_api_key="m"), GeminiClient)
    both = client_for(groq_api_key="g", gemini_api_key="m")
    assert isinstance(both, FallbackClient) and isinstance(both.fallback, GeminiClient)
    deps.get_ai_client.cache_clear()
