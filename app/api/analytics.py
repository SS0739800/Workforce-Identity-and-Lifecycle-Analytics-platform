"""Analytics endpoints. Every number comes from a named query in app/analytics/sql/."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.schemas.analytics import (
    AttributeChangesResponse,
    DataQualityResponse,
    DateRange,
    GroupCleanupResponse,
    LicenseCleanupResponse,
    OffboardingResponse,
    SyncSummaryResponse,
    SyncTrendsResponse,
    WorkflowFailuresResponse,
    WorkflowSummaryResponse,
)
from app.services.analytics_service import run_query

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def date_range(
    start_date: date | None = Query(None, description="First day to include (inclusive)"),
    end_date: date | None = Query(None, description="Last day to include (inclusive)"),
) -> DateRange:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    return DateRange(start_date=start_date, end_date=end_date)


class Queries:
    """Runs named queries for one request, applying the request's date range."""

    def __init__(self, session: Session, period: DateRange):
        self.session = session
        self.period = period

    def rows(self, name: str, **params) -> list[dict]:
        return run_query(self.session, name, self.period.start_date, self.period.end_date, **params)

    def one(self, name: str, **params) -> dict:
        return self.rows(name, **params)[0]


def queries(period: DateRange = Depends(date_range), session: Session = Depends(get_session)) -> Queries:
    return Queries(session, period)


@router.get("/sync-summary", response_model=SyncSummaryResponse)
def sync_summary(q: Queries = Depends(queries)):
    return SyncSummaryResponse(
        period=q.period,
        totals=q.one("sync_summary"),
        failures_by_error_type=q.rows("sync_failures_by_error_type"),
        failures_by_department=q.rows("sync_failures_by_department"),
        failures_by_location=q.rows("sync_failures_by_location"),
        run_durations=q.rows("sync_run_durations"),
    )


@router.get("/sync-trends", response_model=SyncTrendsResponse)
def sync_trends(q: Queries = Depends(queries)):
    return SyncTrendsResponse(period=q.period, months=q.rows("sync_monthly_trend"))


@router.get("/attribute-changes", response_model=AttributeChangesResponse)
def attribute_changes(
    top: int = Query(20, ge=1, le=100, description="How many of the most-changed employees to return"),
    q: Queries = Depends(queries),
):
    return AttributeChangesResponse(
        period=q.period,
        by_attribute=q.rows("attribute_changes_by_attribute"),
        by_department=q.rows("attribute_changes_by_department"),
        most_changed_employees=q.rows("most_changed_employees", limit=top),
    )


@router.get("/workflow-summary", response_model=WorkflowSummaryResponse)
def workflow_summary(q: Queries = Depends(queries)):
    return WorkflowSummaryResponse(
        period=q.period,
        by_type=q.rows("workflow_summary"),
        durations=q.rows("workflow_durations"),
        monthly=q.rows("workflow_monthly_trend"),
        pending=q.rows("pending_workflows"),
    )


@router.get("/workflow-failures", response_model=WorkflowFailuresResponse)
def workflow_failures(
    min_failures: int = Query(3, ge=1, le=100, description="Threshold for the repeated-failures list"),
    q: Queries = Depends(queries),
):
    return WorkflowFailuresResponse(
        period=q.period,
        by_action=q.rows("action_failure_rates"),
        by_error_type=q.rows("action_failures_by_error_type"),
        repeated_failures=q.rows("repeated_operational_failures", min_failures=min_failures),
    )


@router.get("/data-quality", response_model=DataQualityResponse)
def data_quality(q: Queries = Depends(queries)):
    return DataQualityResponse(
        period=q.period,
        totals=q.one("dq_summary"),
        by_type=q.rows("dq_by_type"),
        by_department=q.rows("dq_by_department"),
        monthly=q.rows("dq_monthly_trend"),
        sync_impact=q.rows("sync_failures_with_open_dq_issue"),
        employees_with_open_issues=q.rows("employees_with_open_issues"),
    )


@router.get("/offboarding", response_model=OffboardingResponse)
def offboarding(q: Queries = Depends(queries)):
    return OffboardingResponse(
        period=q.period,
        monthly=q.rows("offboarding_monthly"),
        time_to_disable=q.one("time_to_disable_account"),
        access_remaining=q.rows("access_remaining_after_offboarding"),
    )


@router.get("/group-cleanup", response_model=GroupCleanupResponse)
def group_cleanup(q: Queries = Depends(queries)):
    return GroupCleanupResponse(period=q.period, groups=q.rows("group_cleanup_summary"))


@router.get("/license-cleanup", response_model=LicenseCleanupResponse)
def license_cleanup(q: Queries = Depends(queries)):
    return LicenseCleanupResponse(period=q.period, licenses=q.rows("license_cleanup_summary"))
