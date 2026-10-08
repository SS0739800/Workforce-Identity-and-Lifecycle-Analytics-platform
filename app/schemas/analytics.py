"""Response models for the analytics endpoints.

Field names match the column names in app/analytics/sql/, so each row model documents
exactly what its query returns. Percentages are 0-100 with one decimal place and are
None when there is nothing to divide by.
"""

from datetime import date, datetime

from pydantic import BaseModel


class DateRange(BaseModel):
    start_date: date | None
    end_date: date | None


# --- sync ---------------------------------------------------------------------------

class SyncTotals(BaseModel):
    total_runs: int
    clean_runs: int
    runs_with_errors: int
    failed_runs: int
    records_evaluated: int
    records_updated: int
    records_failed: int
    record_success_rate_pct: float | None
    run_failure_rate_pct: float | None


class ErrorTypeCount(BaseModel):
    error_type: str
    failures: int
    share_pct: float


class DepartmentSyncFailures(BaseModel):
    department: str
    sync_attempts: int
    failures: int
    failure_rate_pct: float


class LocationSyncFailures(BaseModel):
    location: str
    sync_attempts: int
    failures: int
    timeouts: int
    failure_rate_pct: float


class RunDuration(BaseModel):
    triggered_by: str
    runs: int
    avg_seconds: float
    p90_seconds: float
    max_seconds: float


class SyncSummaryResponse(BaseModel):
    period: DateRange
    totals: SyncTotals
    failures_by_error_type: list[ErrorTypeCount]
    failures_by_department: list[DepartmentSyncFailures]
    failures_by_location: list[LocationSyncFailures]
    run_durations: list[RunDuration]


class SyncMonth(BaseModel):
    month: date
    runs: int
    failed_runs: int
    records_updated: int
    records_failed: int
    record_failure_rate_pct: float | None


class SyncTrendsResponse(BaseModel):
    period: DateRange
    months: list[SyncMonth]


# --- attribute changes --------------------------------------------------------------

class AttributeChangeCount(BaseModel):
    attribute_name: str
    changes: int
    hr_changes: int
    corrections: int
    employees_affected: int


class DepartmentChangeCount(BaseModel):
    department: str
    changes: int
    employees_changed: int


class EmployeeChangeCount(BaseModel):
    id: int
    employee_id: str | None
    employee_name: str
    department: str | None
    changes: int
    attributes_changed: int


class AttributeChangesResponse(BaseModel):
    period: DateRange
    by_attribute: list[AttributeChangeCount]
    by_department: list[DepartmentChangeCount]
    most_changed_employees: list[EmployeeChangeCount]


# --- workflows ----------------------------------------------------------------------

class WorkflowTypeSummary(BaseModel):
    workflow_type: str
    workflows: int
    completed: int
    failed: int
    pending: int
    service_desk_reruns: int
    success_rate_pct: float | None


class WorkflowDuration(BaseModel):
    workflow_type: str
    workflows: int
    avg_seconds: float
    median_seconds: float
    p90_seconds: float


class WorkflowMonth(BaseModel):
    month: date
    workflow_type: str
    workflows: int
    failed: int


class PendingWorkflow(BaseModel):
    workflow_run_id: int
    workflow_type: str
    requested_at: datetime
    employee_db_id: int
    employee_id: str | None
    employee_name: str
    department: str | None
    termination_date: date | None


class WorkflowSummaryResponse(BaseModel):
    period: DateRange
    by_type: list[WorkflowTypeSummary]
    durations: list[WorkflowDuration]
    monthly: list[WorkflowMonth]
    pending: list[PendingWorkflow]


class ActionFailureRate(BaseModel):
    action_type: str
    attempts: int
    failures: int
    skipped: int
    failure_rate_pct: float | None


class ActionErrorCount(BaseModel):
    action_type: str
    error_type: str
    failures: int


class EmployeeFailureCount(BaseModel):
    employee_db_id: int
    employee_id: str | None
    employee_name: str
    department: str | None
    employment_status: str
    total_failures: int
    sync_failures: int
    workflow_failures: int
    error_types: str


class WorkflowFailuresResponse(BaseModel):
    period: DateRange
    by_action: list[ActionFailureRate]
    by_error_type: list[ActionErrorCount]
    repeated_failures: list[EmployeeFailureCount]


# --- offboarding and cleanup ----------------------------------------------------------

class OffboardingMonth(BaseModel):
    month: date
    offboardings: int
    completed_first_time: int
    failed_first_time: int
    service_desk_reruns: int
    first_time_success_pct: float | None


class TimeToDisable(BaseModel):
    terminated_with_account: int
    still_enabled: int
    disabled_before_termination: int
    disabled_within_4_hours: int
    disabled_within_24_hours: int
    disabled_after_24_hours: int
    median_hours_to_disable: float | None


class RemainingAccess(BaseModel):
    employee_db_id: int
    employee_id: str | None
    employee_name: str
    department: str | None
    termination_date: date | None
    account_status: str | None
    active_groups: int
    active_roles: int
    active_licenses: int


class OffboardingResponse(BaseModel):
    period: DateRange
    monthly: list[OffboardingMonth]
    time_to_disable: TimeToDisable
    access_remaining: list[RemainingAccess]


class GroupCleanup(BaseModel):
    group_name: str
    removal_attempts: int
    removal_failures: int
    failure_rate_pct: float | None
    still_assigned_to_terminated: int


class GroupCleanupResponse(BaseModel):
    period: DateRange
    groups: list[GroupCleanup]


class LicenseCleanup(BaseModel):
    license_name: str
    removal_attempts: int
    removal_failures: int
    failure_rate_pct: float | None
    still_assigned_to_terminated: int


class LicenseCleanupResponse(BaseModel):
    period: DateRange
    licenses: list[LicenseCleanup]


# --- data quality ---------------------------------------------------------------------

class DataQualityTotals(BaseModel):
    total_issues: int
    open_issues: int
    resolved_issues: int
    open_critical_issues: int
    employees_with_open_issues: int
    avg_days_to_resolve: float | None


class IssueTypeCount(BaseModel):
    issue_type: str
    field_name: str
    severity: str
    issues: int
    open_issues: int
    resolved_issues: int
    avg_days_to_resolve: float | None


class DepartmentIssueCount(BaseModel):
    department: str
    issues: int
    open_issues: int
    employees_affected: int


class IssueMonth(BaseModel):
    month: date
    detected: int
    resolved: int


class SyncImpact(BaseModel):
    had_open_issue: bool
    sync_attempts: int
    failures: int
    failure_rate_pct: float


class EmployeeOpenIssues(BaseModel):
    employee_db_id: int
    employee_id: str | None
    employee_name: str
    department: str | None
    employment_status: str
    open_issues: int
    issue_types: str
    highest_severity: str
    oldest_detected_at: datetime


class DataQualityResponse(BaseModel):
    period: DateRange
    totals: DataQualityTotals
    by_type: list[IssueTypeCount]
    by_department: list[DepartmentIssueCount]
    monthly: list[IssueMonth]
    sync_impact: list[SyncImpact]
    employees_with_open_issues: list[EmployeeOpenIssues]
