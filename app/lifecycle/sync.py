"""Rules for the HR -> identity sync: which records it processes, when a record fails,
and which lifecycle workflows a run should start.
"""

import random
from datetime import date, datetime, timedelta
from typing import Mapping

from app.lifecycle import failures
from app.lifecycle.validation import check_hr_record

# A failing record is retried on this many runs, then held until its HR data changes again.
MAX_SYNC_ATTEMPTS = 3
# Terminated employees stay in the HR export for this many days after their termination date.
EXPORT_TERMINATED_RETENTION_DAYS = 30


def in_hr_export(employee: Mapping, when: datetime) -> bool:
    """The HR file contains everyone not terminated, plus recent leavers."""
    if employee["created_at"] > when:
        return False
    if employee["employment_status"] == "terminated" and employee["termination_date"]:
        cutoff = when.date() - timedelta(days=EXPORT_TERMINATED_RETENTION_DAYS)
        return employee["termination_date"] >= cutoff
    return True


def needs_attribute_sync(
    employment_status: str,
    has_account: bool,
    onboarding_started: bool,
    changed_since_last_sync: bool,
    failed_attempts: int,
) -> bool:
    """Whether the sync should try to process this record on this run."""
    if employment_status != "active":
        return False  # terminated records are handled by offboarding, not the attribute sync
    if failed_attempts >= MAX_SYNC_ATTEMPTS:
        return False  # held until the HR record changes
    if not has_account:
        return not onboarding_started  # new hire: hand over to onboarding once
    return changed_since_last_sync


def sync_record_error(
    employee: Mapping,
    as_of: date,
    duplicate_of: int | None,
    manager_has_no_account: bool,
    rng: random.Random,
) -> tuple[str, str] | None:
    """(error_type, message) if the record cannot be synced, otherwise None.

    The checks mirror the original automation: required attributes first, then the
    manager lookup, then the directory call itself (which can time out).
    """
    blocking = [f for f in check_hr_record(employee, as_of, duplicate_of) if f.blocks_sync]
    if blocking:
        return blocking[0].error_type, " ".join(f.description for f in blocking)
    if manager_has_no_account:
        return "RESOURCE_NOT_FOUND", "Manager's identity account was not found."
    if failures.roll_sync_timeout(rng):
        return "TIMEOUT", "Directory update timed out after 30 seconds."
    return None


def due_workflows(
    employee: Mapping,
    has_account: bool,
    already_offboarded: bool,
    has_pending_offboarding: bool,
    leave_applied: bool,
    today: date,
) -> list[str]:
    """Lifecycle work a sync run should start for this employee, based on HR status.

    Returns any of: 'offboarding', 'queue_offboarding' (future-dated termination),
    'leave', 'return_from_leave'.
    """
    if employee["employment_status"] == "terminated":
        return [] if already_offboarded else ["offboarding"]

    due = []
    termination_date = employee["termination_date"]
    if termination_date and termination_date >= today and not has_pending_offboarding and has_account:
        due.append("queue_offboarding")
    if employee["leave_status"] == "on_leave" and not leave_applied:
        due.append("leave")
    elif employee["leave_status"] == "none" and leave_applied:
        due.append("return_from_leave")
    return due
