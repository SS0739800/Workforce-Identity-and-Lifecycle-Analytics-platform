"""Validation rules for HR records and identity state.

The same rules serve two purposes:
- the attribute sync refuses to process a record when a *blocking* rule fails
  (mirroring how the original automation skipped records missing an employee ID,
  manager ID or title, except that here the failure is recorded instead of silently skipped);
- the daily data-quality scan turns every failing rule into a data_quality_issues row.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping

from app.lifecycle.reference import CEO_TITLE, LOCATIONS, valid_departments

EMAIL_PATTERN = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*@[a-z0-9-]+(\.[a-z0-9-]+)+$")

# New hires get a few days for onboarding to run before a missing account counts as a problem.
ACCOUNT_GRACE_PERIOD = timedelta(days=3)


@dataclass(frozen=True)
class Finding:
    issue_type: str
    field_name: str
    severity: str
    description: str
    blocks_sync: bool = False
    # Error type recorded on the sync result when this finding blocks a record.
    error_type: str | None = None


def check_hr_record(employee: Mapping, as_of: date, duplicate_of: int | None = None) -> list[Finding]:
    """Rules that only need the HR record itself (plus the result of duplicate detection)."""
    findings: list[Finding] = []
    status = employee["employment_status"]

    if status == "active":
        if not employee["employee_id"]:
            findings.append(Finding(
                "missing_employee_id", "employee_id", "high",
                "Employee ID is blank; the record cannot be matched to an identity account.",
                blocks_sync=True, error_type="MISSING_ATTRIBUTE",
            ))
        if duplicate_of is not None:
            findings.append(Finding(
                "duplicate_employee", "employee_record", "high",
                f"Same name and hire date as employee record {duplicate_of}.",
                blocks_sync=True, error_type="VALIDATION_ERROR",
            ))
        email = employee["email"]
        if not email or not EMAIL_PATTERN.match(email):
            findings.append(Finding(
                "invalid_email", "email", "high",
                "Email address is missing or not in a valid format.",
                blocks_sync=True, error_type="VALIDATION_ERROR",
            ))
        department = employee["department"]
        if department not in valid_departments(as_of):
            findings.append(Finding(
                "invalid_department", "department", "medium",
                f"Department '{department}' is not in the approved department list.",
                blocks_sync=True, error_type="INVALID_ATTRIBUTE",
            ))
        if not employee["job_title"]:
            findings.append(Finding(
                "missing_job_title", "job_title", "medium",
                "Job title is blank; role assignment cannot be determined.",
                blocks_sync=True, error_type="MISSING_ATTRIBUTE",
            ))
        if employee["manager_id"] is None and employee["job_title"] != CEO_TITLE:
            findings.append(Finding(
                "missing_manager", "manager_id", "medium",
                "Manager is blank.",
                blocks_sync=True, error_type="MISSING_ATTRIBUTE",
            ))
        if employee["location"] not in LOCATIONS:
            findings.append(Finding(
                "invalid_location", "location", "low",
                f"Location '{employee['location']}' does not match a known site.",
            ))
        termination_date = employee["termination_date"]
        if termination_date is not None and termination_date < as_of:
            findings.append(Finding(
                "incorrect_employment_status", "employment_status", "critical",
                f"Termination date {termination_date} has passed but status is still active; "
                "offboarding has not been triggered.",
            ))

    if status == "terminated" and employee["termination_date"] is None:
        findings.append(Finding(
            "missing_termination_date", "termination_date", "medium",
            "Employee is terminated but has no termination date.",
        ))

    return findings


def check_identity_state(
    employee: Mapping,
    as_of: datetime,
    account_status: str | None,
    active_groups: int,
    active_roles: int,
    active_licenses: int,
    is_duplicate: bool = False,
) -> list[Finding]:
    """Rules comparing the HR record with the identity account and its access."""
    findings: list[Finding] = []
    status = employee["employment_status"]

    if status == "active":
        old_enough = employee["created_at"] <= as_of - ACCOUNT_GRACE_PERIOD
        if account_status is None and old_enough and not is_duplicate:
            findings.append(Finding(
                "missing_identity_account", "identity_account", "high",
                "Active employee has no identity account.",
            ))
        return findings

    # Offboarding runs overnight, so leftover access only counts as a problem from the day
    # after the termination date. Without a date, fall back to when the record last changed.
    terminated_on = employee["termination_date"] or employee["updated_at"].date()
    if as_of.date() <= terminated_on:
        return findings

    if account_status == "active":
        findings.append(Finding(
            "active_account_for_terminated_employee", "account_status", "critical",
            "Identity account is still enabled after termination.",
        ))
    if active_groups:
        findings.append(Finding(
            "stale_group_membership", "group_membership", "medium",
            f"{active_groups} group membership(s) remain after termination.",
        ))
    if active_roles:
        findings.append(Finding(
            "stale_role_assignment", "role_assignment", "high",
            f"{active_roles} role assignment(s) remain after termination.",
        ))
    if active_licenses:
        findings.append(Finding(
            "license_on_inactive_employee", "license_assignment", "medium",
            f"{active_licenses} license(s) still assigned after termination.",
        ))
    return findings


def find_duplicates(employees: list[Mapping]) -> dict[int, int]:
    """Map each duplicate record's id to the id of the earlier record it duplicates.

    Two records are treated as the same person when first name, last name and hire date match.
    """
    first_seen: dict[tuple, int] = {}
    duplicates: dict[int, int] = {}
    for employee in sorted(employees, key=lambda e: e["id"]):
        key = (employee["first_name"].lower(), employee["last_name"].lower(), employee["hire_date"])
        if key in first_seen:
            duplicates[employee["id"]] = first_seen[key]
        else:
            first_seen[key] = employee["id"]
    return duplicates


# --- the data-quality scan ------------------------------------------------------------------

@dataclass(frozen=True)
class AccessSnapshot:
    """An employee's identity account status and how many active assignments they hold."""

    account_status: str | None = None
    groups: int = 0
    roles: int = 0
    licenses: int = 0


IssueKey = tuple[int, str]  # (employees.id, issue_type)


def find_issues(
    employees: list[Mapping],
    access: Mapping[int, AccessSnapshot],
    as_of: datetime,
) -> dict[IssueKey, Finding]:
    """Run every rule against every employee record."""
    duplicates = find_duplicates(employees)
    found: dict[IssueKey, Finding] = {}
    for employee in employees:
        snapshot = access.get(employee["id"], AccessSnapshot())
        findings = check_hr_record(employee, as_of.date(), duplicates.get(employee["id"]))
        findings += check_identity_state(
            employee,
            as_of,
            snapshot.account_status,
            snapshot.groups,
            snapshot.roles,
            snapshot.licenses,
            is_duplicate=employee["id"] in duplicates,
        )
        for finding in findings:
            found[(employee["id"], finding.issue_type)] = finding
    return found


def issue_changes(open_issues: list[IssueKey], found: Mapping[IssueKey, Finding]) -> tuple[list[IssueKey], list[IssueKey]]:
    """(issues to open, issues to resolve) when comparing a new scan with the issues already open."""
    already_open = set(open_issues)
    to_open = [key for key in found if key not in already_open]
    to_resolve = [key for key in open_issues if key not in found]
    return to_open, to_resolve
