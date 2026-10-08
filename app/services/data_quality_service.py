"""Run the data-quality scan against the database, using the same rules as the simulator."""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.lifecycle.validation import AccessSnapshot, find_issues, issue_changes
from app.models import DataQualityIssue, Employee, GroupMembership, IdentityAccount, LicenseAssignment, RoleAssignment
from app.services.identity_store import employee_record

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    scanned_at: datetime
    employees_scanned: int
    issues_opened: int
    issues_resolved: int
    open_issues: int


def _active_counts(session: Session, model) -> dict[int, int]:
    rows = session.execute(
        select(model.employee_id, func.count()).where(model.status == "active").group_by(model.employee_id)
    )
    return dict(rows.all())


def run_scan(session: Session, now: datetime) -> ScanResult:
    """Open an issue for every rule that fails and resolve open issues that no longer fail."""
    employees = [
        employee_record(e)
        for e in session.scalars(select(Employee).where(Employee.created_at <= now).order_by(Employee.id))
    ]
    account_status = dict(session.execute(select(IdentityAccount.employee_id, IdentityAccount.account_status)).all())
    groups = _active_counts(session, GroupMembership)
    roles = _active_counts(session, RoleAssignment)
    licenses = _active_counts(session, LicenseAssignment)
    access = {
        e["id"]: AccessSnapshot(
            account_status.get(e["id"]), groups.get(e["id"], 0), roles.get(e["id"], 0), licenses.get(e["id"], 0)
        )
        for e in employees
    }
    found = find_issues(employees, access, now)

    open_issues = {
        (issue.employee_id, issue.issue_type): issue
        for issue in session.scalars(select(DataQualityIssue).where(DataQualityIssue.status == "open"))
    }
    to_open, to_resolve = issue_changes(list(open_issues), found)

    for key in to_open:
        finding = found[key]
        session.add(DataQualityIssue(
            employee_id=key[0],
            issue_type=finding.issue_type,
            field_name=finding.field_name,
            severity=finding.severity,
            description=finding.description,
            detected_at=now,
            status="open",
        ))
    for key in to_resolve:
        issue = open_issues[key]
        issue.status = "resolved"
        issue.resolved_at = now
    session.flush()

    result = ScanResult(
        scanned_at=now,
        employees_scanned=len(employees),
        issues_opened=len(to_open),
        issues_resolved=len(to_resolve),
        open_issues=len(found),
    )
    logger.info("Data-quality scan: %d opened, %d resolved, %d open", len(to_open), len(to_resolve), len(found))
    return result
