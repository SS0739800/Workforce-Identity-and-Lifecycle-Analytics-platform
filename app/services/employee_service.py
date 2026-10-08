"""Employee lookups for the investigation screens.

`employee_db_id` is employees.id (the surrogate key). The HR employee ID (EMP00042) can be
missing or duplicated, so it is searchable but not used to address a record.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AttributeChangeLog,
    AuditEvent,
    DataQualityIssue,
    Employee,
    GroupMembership,
    IdentityAccount,
    LicenseAssignment,
    RoleAssignment,
    SyncRecordResult,
    WorkflowAction,
    WorkflowRun,
)
from app.schemas.employee import (
    AccessAssignment,
    ActivityEvent,
    DataQualityIssueOut,
    EmployeeDetail,
    EmployeeSummary,
    IdentityAccountOut,
    ManagerRef,
)
from app.schemas.workflow import WorkflowActionOut, WorkflowRunOut


class EmployeeNotFound(Exception):
    pass


def list_employees(
    session: Session,
    search: str | None,
    department: str | None,
    employment_status: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[Employee]]:
    query = select(Employee)
    if search:
        pattern = f"%{search.strip()}%"
        full_name = Employee.first_name + " " + Employee.last_name
        query = query.where(or_(
            Employee.employee_id.ilike(pattern),
            Employee.email.ilike(pattern),
            full_name.ilike(pattern),
        ))
    if department:
        query = query.where(Employee.department == department)
    if employment_status:
        query = query.where(Employee.employment_status == employment_status)

    total = session.scalar(select(func.count()).select_from(query.subquery()))
    employees = session.scalars(query.order_by(Employee.id).limit(limit).offset(offset)).all()
    return total, list(employees)


def get_employee(session: Session, employee_db_id: int) -> Employee:
    employee = session.get(Employee, employee_db_id)
    if employee is None:
        raise EmployeeNotFound(employee_db_id)
    return employee


def _assignments(session: Session, model, name_column, employee_db_id: int) -> list[AccessAssignment]:
    rows = session.scalars(
        select(model).where(model.employee_id == employee_db_id).order_by(model.assigned_at, model.id)
    ).all()
    return [
        AccessAssignment(
            name=getattr(row, name_column),
            status=row.status,
            assigned_at=row.assigned_at,
            removed_at=row.removed_at,
        )
        for row in rows
    ]


def get_employee_detail(session: Session, employee_db_id: int) -> EmployeeDetail:
    employee = get_employee(session, employee_db_id)

    manager = None
    if employee.manager_id is not None:
        boss = session.get(Employee, employee.manager_id)
        manager = ManagerRef(
            id=boss.id,
            employee_id=boss.employee_id,
            name=f"{boss.first_name} {boss.last_name}",
            employment_status=boss.employment_status,
        )

    account = session.scalar(select(IdentityAccount).where(IdentityAccount.employee_id == employee_db_id))
    issues = session.scalars(
        select(DataQualityIssue)
        .where(DataQualityIssue.employee_id == employee_db_id)
        .order_by(DataQualityIssue.detected_at.desc())
    ).all()

    return EmployeeDetail(
        **EmployeeSummary.model_validate(employee).model_dump(),
        manager=manager,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
        identity_account=IdentityAccountOut.model_validate(account) if account else None,
        groups=_assignments(session, GroupMembership, "group_name", employee_db_id),
        roles=_assignments(session, RoleAssignment, "role_name", employee_db_id),
        licenses=_assignments(session, LicenseAssignment, "license_name", employee_db_id),
        data_quality_issues=[DataQualityIssueOut.model_validate(issue) for issue in issues],
    )


def get_activity(session: Session, employee_db_id: int, limit: int) -> list[ActivityEvent]:
    """One timeline: identity audit events, failed sync attempts, and data-quality findings."""
    get_employee(session, employee_db_id)
    events: list[ActivityEvent] = []

    for audit in session.scalars(select(AuditEvent).where(AuditEvent.employee_id == employee_db_id)):
        events.append(ActivityEvent(
            timestamp=audit.event_timestamp,
            category="audit",
            event_type=audit.event_type,
            description=audit.description,
            source=audit.source,
        ))

    failed_syncs = select(SyncRecordResult).where(
        SyncRecordResult.employee_id == employee_db_id, SyncRecordResult.status == "failed"
    )
    for result in session.scalars(failed_syncs):
        events.append(ActivityEvent(
            timestamp=result.started_at,
            category="sync",
            event_type=f"sync_failed:{result.error_type}",
            description=result.error_message or "",
            source="identity_sync",
        ))

    for issue in session.scalars(select(DataQualityIssue).where(DataQualityIssue.employee_id == employee_db_id)):
        events.append(ActivityEvent(
            timestamp=issue.detected_at,
            category="data_quality",
            event_type=f"issue_detected:{issue.issue_type}",
            description=issue.description,
            source="data_quality_scan",
        ))
        if issue.resolved_at:
            events.append(ActivityEvent(
                timestamp=issue.resolved_at,
                category="data_quality",
                event_type=f"issue_resolved:{issue.issue_type}",
                description="Rule no longer fails for this record.",
                source="data_quality_scan",
            ))

    events.sort(key=lambda event: event.timestamp, reverse=True)
    return events[:limit]


def get_workflows(session: Session, employee_db_id: int) -> list[WorkflowRunOut]:
    get_employee(session, employee_db_id)
    runs = session.scalars(
        select(WorkflowRun).where(WorkflowRun.employee_id == employee_db_id).order_by(WorkflowRun.requested_at.desc())
    ).all()
    if not runs:
        return []

    actions_by_run: dict[int, list[WorkflowActionOut]] = {run.id: [] for run in runs}
    actions = session.scalars(
        select(WorkflowAction)
        .where(WorkflowAction.workflow_run_id.in_(actions_by_run))
        .order_by(WorkflowAction.started_at, WorkflowAction.id)
    )
    for action in actions:
        actions_by_run[action.workflow_run_id].append(WorkflowActionOut.model_validate(action))

    return [
        WorkflowRunOut(
            id=run.id,
            workflow_type=run.workflow_type,
            status=run.status,
            initiated_by=run.initiated_by,
            requested_at=run.requested_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            actions=actions_by_run[run.id],
        )
        for run in runs
    ]


def get_changes(session: Session, employee_db_id: int) -> list[AttributeChangeLog]:
    get_employee(session, employee_db_id)
    return list(session.scalars(
        select(AttributeChangeLog)
        .where(AttributeChangeLog.employee_id == employee_db_id)
        .order_by(AttributeChangeLog.changed_at.desc(), AttributeChangeLog.id.desc())
    ))
