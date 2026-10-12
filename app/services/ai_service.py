"""AI insights: facts come from SQL, Groq only explains them.

Every insight follows the same steps:
1. compute the facts with approved queries,
2. remove personal fields,
3. ask Groq for an explanation (skipped if Groq is not configured or fails),
4. check every number in the answer against the facts,
5. log the request in ai_insight_runs (sanitized summaries only).

Without Groq, each insight still returns its facts, and the executive summary and incident
report fall back to a plain template written from the same facts.
"""

import logging
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.client import AIError
from app.ai.fallback import AIClient
from app.ai.grounding import ungrounded_numbers
from app.ai.prompts import SYSTEM_PROMPT, build_user_message
from app.ai.router import parse_period, route_by_keywords, route_with_ai
from app.ai.sanitize import contains_personal_data, sanitize
from app.analytics.queries import QUERIES
from app.models import (
    AIInsightRun,
    Employee,
    GroupMembership,
    IdentityAccount,
    LicenseAssignment,
    RoleAssignment,
    SyncRun,
    WorkflowAction,
    WorkflowRun,
)
from app.services.analytics_service import run_query
from app.services.workflow_service import WorkflowNotFound

logger = logging.getLogger(__name__)

MAX_ROWS_TO_AI = 25
SUMMARY_LENGTH = 500

EXAMPLE_QUESTIONS = [
    "Which departments had the most synchronization failures this quarter?",
    "What were the most common offboarding failures last month?",
    "Why do sync records fail?",
    "Which licenses fail to be removed at offboarding?",
    "What are the most common data-quality issues?",
    "How quickly are accounts disabled after termination?",
]

# Generic checks an analyst would start with for each error type. They are labelled as
# places to look, never as causes, in both the AI prompt and the template fallback.
INVESTIGATION_AREAS = {
    "TIMEOUT": "Response times of the target service around the failure time; whether other actions timed out in the same run.",
    "DEPENDENCY_ERROR": "Availability and throttling limits of the dependent service (directory, licensing, token service) at that time.",
    "PERMISSION_ERROR": "Rights of the automation account on the affected object, especially for privileged roles.",
    "RESOURCE_NOT_FOUND": "Whether the group, account or license still exists, or was renamed or removed by hand.",
    "VALIDATION_ERROR": "The values sent for this employee against the target system's rules.",
    "MISSING_ATTRIBUTE": "The employee's HR record for blank required fields.",
    "INVALID_ATTRIBUTE": "The employee's HR record against the current reference data (departments, sites).",
    "ALREADY_DISABLED": "Whether the account was disabled manually before the workflow ran.",
}


class IncidentNotApplicable(Exception):
    """Incident reports are only written for failed workflows."""


@dataclass
class InsightResult:
    insight_type: str
    facts: dict
    explanation: str | None
    ai_status: str
    model: str | None = None
    ungrounded_numbers: list[str] = field(default_factory=list)
    message: str | None = None
    run_id: int | None = None


def latest_data_date(session: Session) -> date:
    """Relative time phrases are resolved against the most recent sync run, not today's date."""
    latest = session.scalar(select(func.max(SyncRun.started_at)))
    return latest.date() if latest else datetime.now(timezone.utc).date()


def _explain(
    session: Session,
    client: AIClient | None,
    insight_type: str,
    task: str,
    facts: dict,
    input_summary: str,
    question: str | None = None,
    fallback: str | None = None,
) -> InsightResult:
    facts = sanitize(facts)
    if contains_personal_data(facts):  # defence in depth: never send if anything slipped through
        raise ValueError("Personal data found in AI facts after sanitizing")

    explanation, model, ungrounded, message = None, None, [], None
    if client is None:
        status = "unavailable"
        message = "AI is not configured (no GROQ_API_KEY), so only the computed data is shown."
    else:
        model = client.model
        try:
            response = client.complete(SYSTEM_PROMPT, build_user_message(task, facts, question))
            explanation, model = response.text, response.model
            ungrounded = ungrounded_numbers(explanation, facts, question)
            status = "needs_review" if ungrounded else "ok"
            if ungrounded:
                message = "Some numbers in the explanation are not in the computed data; check them before using it."
        except AIError as error:
            status = error.status
            message = f"{error} - showing the computed data only."
            logger.warning("AI request failed for %s: %s", insight_type, error)

    from_ai = explanation is not None
    if not from_ai and fallback:
        explanation = fallback
        message = (message or "") + " A plain summary written from the same data is shown instead."

    log = AIInsightRun(
        insight_type=insight_type,
        requested_at=datetime.now(timezone.utc),
        input_summary=input_summary[:SUMMARY_LENGTH],
        output_summary=explanation[:SUMMARY_LENGTH] if from_ai else None,
        model=model,
        status=status,
        error_message=None if status in ("ok", "needs_review") else message,
    )
    session.add(log)
    session.flush()
    logger.info("AI insight %s: %s", insight_type, status)
    return InsightResult(insight_type, facts, explanation, status, model, ungrounded, message, log.id)


# --- natural-language questions ----------------------------------------------------------------

def ask(session: Session, client: AIClient | None, question: str, as_of: date | None = None) -> InsightResult:
    route = route_by_keywords(question)
    if route is None and client is not None:
        route = route_with_ai(question, client)
    if route is None:
        facts = {"answered": False, "example_questions": EXAMPLE_QUESTIONS}
        session.add(AIInsightRun(
            insight_type="question", requested_at=datetime.now(timezone.utc),
            input_summary="Question did not match an approved query", status="unmatched",
        ))
        session.flush()
        return InsightResult("question", facts, None, "unmatched",
                             message="This question doesn't match an approved query. Try one of the examples.")

    period = parse_period(question, as_of or latest_data_date(session))
    rows = run_query(session, route.query, period.start, period.end, **route.params)
    facts = {
        "query": route.query,
        "query_answers": QUERIES[route.query].question,
        "parameters": route.params,
        "period": {"description": period.description, "start": period.start, "end": period.end},
        "row_count": len(rows),
        "rows": rows[:MAX_ROWS_TO_AI],
    }
    summary = (f"Routed by {route.method} to {route.query}; period {period.description}; "
               f"{len(rows)} rows")
    if not rows:
        # Nothing to explain: say so rather than asking the model to talk about nothing.
        session.add(AIInsightRun(insight_type="question", requested_at=datetime.now(timezone.utc),
                                 input_summary=summary, status="no_data"))
        session.flush()
        return InsightResult("question", sanitize(facts), None, "no_data",
                             message=f"The {route.query} query returned no rows for {period.description}.")
    return _explain(session, client, "question", "question", facts, summary, question=question)


# --- failure explanation -----------------------------------------------------------------------

def explain_failures(session: Session, client: AIClient | None, question: str) -> InsightResult:
    facts = {
        "action_failure_rates": run_query(session, "action_failure_rates"),
        "failures_by_action_and_error_type": run_query(session, "action_failures_by_error_type")[:MAX_ROWS_TO_AI],
    }
    return _explain(session, client, "failure_explanation", "failure_explanation", facts,
                    "Action failure rates and error types (all data)", question=question)


# --- executive summary ----------------------------------------------------------------------

def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def monthly_metrics(session: Session, month: date) -> dict:
    start = month.replace(day=1)
    end = month.replace(day=monthrange(month.year, month.month)[1])

    sync = run_query(session, "sync_summary", start, end)[0]
    workflows = {row["workflow_type"]: row for row in run_query(session, "workflow_summary", start, end)}
    completed = sum(row["completed"] for row in workflows.values())
    failed = sum(row["failed"] for row in workflows.values())
    top_failure = next(iter(run_query(session, "action_failures_by_error_type", start, end)), None)
    departments = [row for row in run_query(session, "sync_failures_by_department", start, end) if row["failures"]]
    open_issues = run_query(session, "dq_summary")[0]["open_issues"]

    return {
        "month": start.strftime("%B %Y"),
        "sync_runs": sync["total_runs"],
        "sync_records_processed": sync["records_updated"] + sync["records_failed"],
        "sync_success_rate_pct": sync["record_success_rate_pct"],
        "offboarding_workflows": workflows.get("offboarding", {}).get("workflows", 0),
        "workflows": sum(row["workflows"] for row in workflows.values()),
        "workflow_failure_rate_pct": _pct(failed, completed + failed),
        "most_common_failure": (
            {"action_type": top_failure["action_type"], "error_type": top_failure["error_type"],
             "failures": top_failure["failures"]} if top_failure else None
        ),
        "open_data_quality_issues_now": open_issues,
        "department_with_most_sync_failures": (
            {"department": departments[0]["department"], "failures": departments[0]["failures"]}
            if departments else None
        ),
    }


def _summary_template(m: dict) -> str:
    failure = m["most_common_failure"]
    department = m["department_with_most_sync_failures"]
    lines = [
        f"Identity operations summary - {m['month']}",
        f"- Sync: {m['sync_runs']} runs, {m['sync_records_processed']} records processed, "
        f"{m['sync_success_rate_pct']}% success rate",
        f"- Offboarding: {m['offboarding_workflows']} workflows",
        f"- Workflows: {m['workflows']} in total, {m['workflow_failure_rate_pct']}% failure rate",
        "- Most common failure: " + (
            f"{failure['action_type']} ({failure['error_type']}), {failure['failures']} times" if failure else "none"),
        f"- Open data-quality issues (current): {m['open_data_quality_issues_now']}",
        "- Department with most sync failures: " + (
            f"{department['department']} ({department['failures']})" if department else "none"),
    ]
    return "\n".join(lines)


def executive_summary(session: Session, client: AIClient | None, month: date) -> InsightResult:
    metrics = monthly_metrics(session, month)
    return _explain(session, client, "executive_summary", "executive_summary", metrics,
                    f"Monthly metrics for {metrics['month']}", fallback=_summary_template(metrics))


# --- data quality ----------------------------------------------------------------------------

def explain_data_quality(session: Session, client: AIClient | None) -> InsightResult:
    facts = {
        "summary": run_query(session, "dq_summary")[0],
        "by_type": run_query(session, "dq_by_type")[:15],
        "by_department": run_query(session, "dq_by_department")[:10],
        "sync_failure_rate_with_and_without_open_issue": run_query(session, "sync_failures_with_open_dq_issue"),
    }
    return _explain(session, client, "data_quality", "data_quality", facts,
                    "Data-quality summary, types, departments and sync association (all data)",
                    question="What are the most significant data-quality problems?")


# --- incident report --------------------------------------------------------------------------

def incident_facts(session: Session, workflow_run_id: int) -> dict:
    run = session.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise WorkflowNotFound(workflow_run_id)
    if run.status != "failed":
        raise IncidentNotApplicable(f"Workflow {run.id} is {run.status}; incident reports are for failed workflows")

    employee = session.get(Employee, run.employee_id)
    actions = list(session.scalars(
        select(WorkflowAction).where(WorkflowAction.workflow_run_id == run.id)
        .order_by(WorkflowAction.started_at, WorkflowAction.id)
    ))
    failed = [a for a in actions if a.status == "failed"]
    overall = {row["action_type"]: row for row in run_query(session, "action_failure_rates")}

    def active_count(model) -> int:
        return session.scalar(select(func.count()).select_from(model).where(
            model.employee_id == employee.id, model.status == "active")) or 0

    account = session.scalar(select(IdentityAccount).where(IdentityAccount.employee_id == employee.id))
    window_start = run.started_at - timedelta(days=30)
    same_error_recently = {
        a.error_type: session.scalar(select(func.count()).select_from(WorkflowAction).where(
            WorkflowAction.error_type == a.error_type,
            WorkflowAction.started_at >= window_start,
            WorkflowAction.started_at < run.started_at,
        ))
        for a in failed
    }
    later_reruns = session.scalars(select(WorkflowRun).where(
        WorkflowRun.employee_id == employee.id,
        WorkflowRun.workflow_type == run.workflow_type,
        WorkflowRun.initiated_by == "service_desk",
        WorkflowRun.requested_at > run.requested_at,
    )).all()
    other_workflows = session.scalars(select(WorkflowRun).where(
        WorkflowRun.employee_id == employee.id, WorkflowRun.id != run.id)).all()

    return {
        "workflow": {
            "workflow_run_id": run.id, "workflow_type": run.workflow_type, "status": run.status,
            "initiated_by": run.initiated_by, "requested_at": run.requested_at,
            "started_at": run.started_at, "completed_at": run.completed_at,
        },
        "employee": {
            "hr_employee_id": employee.employee_id, "department": employee.department,
            "job_title": employee.job_title, "location": employee.location,
            "employment_status": employee.employment_status,
        },
        "timeline": [
            {"action_type": a.action_type, "target": a.target_name, "status": a.status,
             "started_at": a.started_at, "completed_at": a.completed_at, "error_type": a.error_type}
            for a in actions
        ],
        "failed_actions": [
            {"action_type": a.action_type, "target": a.target_name, "error_type": a.error_type,
             "error_message": a.error_message}
            for a in failed
        ],
        "observed_impact_now": {
            "account_status": account.account_status if account else "no account",
            "active_groups": active_count(GroupMembership),
            "active_roles": active_count(RoleAssignment),
            "active_licenses": active_count(LicenseAssignment),
        },
        "historical_context": {
            "overall_failure_rate_pct_for_failed_action_types": {
                a.action_type: overall[a.action_type]["failure_rate_pct"] for a in failed if a.action_type in overall
            },
            "same_error_type_in_previous_30_days": same_error_recently,
            "service_desk_reruns_after_this_failure": len(later_reruns),
            "rerun_outcomes": [r.status for r in later_reruns],
            "other_workflows_for_this_employee": len(other_workflows),
            "other_failed_workflows_for_this_employee": sum(r.status == "failed" for r in other_workflows),
        },
        "investigation_checklist_by_error_type": {
            a.error_type: INVESTIGATION_AREAS[a.error_type] for a in failed if a.error_type in INVESTIGATION_AREAS
        },
    }


def _incident_template(f: dict) -> str:
    w, e, h = f["workflow"], f["employee"], f["historical_context"]
    lines = [
        f"Incident: {w['workflow_type']} workflow {w['workflow_run_id']} failed",
        "",
        "Observed",
        f"- Employee {e['hr_employee_id']} ({e['department']}, {e['location']}), currently {e['employment_status']}",
        f"- Started {w['started_at']} by {w['initiated_by']}, completed {w['completed_at']}",
    ]
    for action in f["failed_actions"]:
        target = f" '{action['target']}'" if action["target"] else ""
        lines.append(f"- Failed: {action['action_type']}{target} - {action['error_type']}: {action['error_message']}")
    impact = f["observed_impact_now"]
    lines += [
        f"- Now: account {impact['account_status']}, {impact['active_groups']} groups, "
        f"{impact['active_roles']} roles, {impact['active_licenses']} licenses still active",
        f"- Service-desk re-runs since: {h['service_desk_reruns_after_this_failure']} "
        f"({', '.join(h['rerun_outcomes']) or 'none'})",
        "",
        "Potential investigation areas (to check, not conclusions)",
    ]
    lines += [f"- {error_type}: {area}" for error_type, area in f["investigation_checklist_by_error_type"].items()]
    return "\n".join(lines)


def incident_report(session: Session, client: AIClient | None, workflow_run_id: int) -> InsightResult:
    facts = incident_facts(session, workflow_run_id)
    w = facts["workflow"]
    return _explain(session, client, "incident_report", "incident_report", facts,
                    f"Failed {w['workflow_type']} workflow {w['workflow_run_id']}",
                    fallback=_incident_template(facts))
