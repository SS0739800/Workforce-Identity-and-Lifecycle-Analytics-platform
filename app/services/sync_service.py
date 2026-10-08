"""Run the HR -> identity sync against the database.

Same rules as the simulated nightly run (app/lifecycle/sync.py): validate changed records,
update the identity account, then start any lifecycle workflows the HR data calls for.
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.lifecycle.reference import access_for_employee
from app.lifecycle.sync import due_workflows, in_hr_export, needs_attribute_sync, sync_record_error
from app.lifecycle.validation import find_duplicates
from app.lifecycle.workflows import (
    access_changes,
    plan_leave,
    plan_offboarding,
    plan_onboarding,
    plan_return_from_leave,
)
from app.models import Employee, IdentityAccount, SyncRecordResult, SyncRun, WorkflowRun
from app.services.identity_store import DatabaseIdentity, employee_record
from app.services.workflow_service import run_workflow

logger = logging.getLogger(__name__)

# Only one sync may run at a time; this key identifies the sync's PostgreSQL advisory lock.
SYNC_LOCK_KEY = 70_001


class SyncAlreadyRunning(Exception):
    pass


@dataclass
class SyncOutcome:
    run: SyncRun
    workflows_started: list[WorkflowRun]


def run_sync(session: Session, now: datetime, rng: random.Random, triggered_by: str = "manual") -> SyncOutcome:
    """Run one sync. Adds everything to the session; the caller commits."""
    locked = session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": SYNC_LOCK_KEY})
    if not locked:
        raise SyncAlreadyRunning("Another sync run is in progress")

    run = SyncRun(
        run_id=_new_run_id(session, now),
        started_at=now,
        status="completed",
        total_records=0,
        successful_records=0,
        failed_records=0,
        skipped_records=0,
        triggered_by=triggered_by,
    )
    session.add(run)
    session.flush()

    employees = list(session.scalars(select(Employee).order_by(Employee.id)))
    records = {e.id: employee_record(e) for e in employees}
    export = [e for e in employees if in_hr_export(records[e.id], now)]
    accounts = {a.employee_id: a for a in session.scalars(select(IdentityAccount))}
    onboarding_started = set(session.scalars(
        select(WorkflowRun.employee_id).where(WorkflowRun.workflow_type == "onboarding")
    ))
    attempts = _failed_attempts_since_last_change(session)
    duplicates = find_duplicates([records[e.id] for e in export])

    clock = now + timedelta(seconds=5)
    successful = failed = 0
    onboarding_queue: list[Employee] = []

    for employee in export:
        account = accounts.get(employee.id)
        changed = account is not None and (account.last_sync_at is None or employee.updated_at > account.last_sync_at)
        if not needs_attribute_sync(
            employment_status=employee.employment_status,
            has_account=account is not None,
            onboarding_started=employee.id in onboarding_started,
            changed_since_last_sync=changed,
            failed_attempts=attempts.get(employee.id, 0),
        ):
            continue

        manager_id = employee.manager_id
        error = sync_record_error(
            records[employee.id],
            clock.date(),
            duplicates.get(employee.id),
            manager_has_no_account=manager_id is not None and manager_id not in accounts,
            rng=rng,
        )
        record_start = clock
        if error is None:
            clock += timedelta(seconds=rng.randint(1, 3))
        elif error[0] == "TIMEOUT":
            clock += timedelta(seconds=30)
        else:
            clock += timedelta(seconds=1)
        session.add(SyncRecordResult(
            sync_run_id=run.id,
            employee_id=employee.id,
            status="failed" if error else "success",
            error_type=error[0] if error else None,
            error_message=error[1] if error else None,
            started_at=record_start,
            completed_at=clock,
        ))

        if error:
            failed += 1
            continue
        successful += 1
        if account is None:
            onboarding_queue.append(employee)  # new hire: onboarding creates the account
        else:
            _update_account(session, employee, clock)

    run.total_records = len(export)
    run.successful_records = successful
    run.failed_records = failed
    run.skipped_records = len(export) - successful - failed
    run.completed_at = clock
    run.status = "completed_with_errors" if failed else "completed"
    session.flush()

    initiated_by = "nightly_sync" if triggered_by == "schedule" else "manual_sync"
    workflows = _start_lifecycle_workflows(session, employees, onboarding_queue, clock, rng, initiated_by)
    logger.info(
        "Sync %s: %d evaluated, %d updated, %d failed, %d workflows started",
        run.run_id, run.total_records, successful, failed, len(workflows),
    )
    return SyncOutcome(run, workflows)


def _new_run_id(session: Session, now: datetime) -> str:
    """SYNC-<date>-<time>, with a suffix if a run already started in the same second."""
    base = f"SYNC-{now:%Y%m%d-%H%M%S}"
    run_id, suffix = base, 2
    while session.scalar(select(SyncRun.id).where(SyncRun.run_id == run_id)) is not None:
        run_id = f"{base}-{suffix}"
        suffix += 1
    return run_id


def _failed_attempts_since_last_change(session: Session) -> dict[int, int]:
    """Failed sync attempts per employee since their HR record last changed.

    Directory outages are not the record's fault, so DEPENDENCY_ERROR does not count.
    """
    rows = session.execute(
        select(SyncRecordResult.employee_id, func.count())
        .join(Employee, Employee.id == SyncRecordResult.employee_id)
        .where(
            SyncRecordResult.status == "failed",
            SyncRecordResult.error_type != "DEPENDENCY_ERROR",
            SyncRecordResult.started_at > Employee.updated_at,
        )
        .group_by(SyncRecordResult.employee_id)
    )
    return dict(rows.all())


def _update_account(session: Session, employee: Employee, when: datetime) -> None:
    identity = DatabaseIdentity(session, employee)
    identity.account.last_sync_at = when
    identity.audit("attributes_synced", "Identity attributes updated from HR record", when, "identity_sync")
    for kind, name, adding in access_changes(identity.state(), access_for_employee(employee_record(employee))):
        if adding:
            identity.assign(kind, name, when, "identity_sync")
        else:
            identity.unassign(kind, name, when, "identity_sync")


def _start_lifecycle_workflows(
    session: Session,
    employees: list[Employee],
    onboarding_queue: list[Employee],
    clock: datetime,
    rng: random.Random,
    initiated_by: str,
) -> list[WorkflowRun]:
    started: list[WorkflowRun] = []
    clock += timedelta(seconds=5)

    for employee in onboarding_queue:
        identity = DatabaseIdentity(session, employee)
        plan = plan_onboarding(identity.state(), access_for_employee(employee_record(employee)))
        run = run_workflow(session, identity, "onboarding", plan, clock, rng, initiated_by)
        started.append(run)
        clock = run.completed_at + timedelta(seconds=rng.randint(2, 10))

    session.flush()
    has_account = set(session.scalars(select(IdentityAccount.employee_id)))
    duplicates = find_duplicates([employee_record(e) for e in employees])
    history = _workflow_history(session)

    for employee in employees:
        # Duplicate HR records are not real people, so no lifecycle work runs for them.
        if employee.id in duplicates or employee.created_at > clock:
            continue
        employee_history = history.get(employee.id, {})
        pending_offboarding = employee_history.get("pending_offboarding")
        due = due_workflows(
            employee_record(employee),
            has_account=employee.id in has_account,
            already_offboarded=employee_history.get("offboarded", False),
            has_pending_offboarding=pending_offboarding is not None,
            leave_applied=employee_history.get("last_leave_type") == "leave",
            today=clock.date(),
        )
        for work in due:
            run = _start(session, employee, work, pending_offboarding, clock, rng, initiated_by)
            if run is not None:
                started.append(run)
                clock = run.completed_at + timedelta(seconds=rng.randint(2, 10))

    session.flush()
    return started


def _start(
    session: Session,
    employee: Employee,
    work: str,
    pending_offboarding: WorkflowRun | None,
    clock: datetime,
    rng: random.Random,
    initiated_by: str,
) -> WorkflowRun | None:
    """Start one piece of lifecycle work. Returns the executed run, or None if nothing ran."""
    if work == "queue_offboarding":
        # Future-dated termination: queue offboarding so it shows up as pending work.
        session.add(WorkflowRun(
            employee_id=employee.id,
            workflow_type="offboarding",
            requested_at=clock,
            status="pending",
            initiated_by=initiated_by,
        ))
        return None

    identity = DatabaseIdentity(session, employee)
    if work == "offboarding":
        plan = plan_offboarding(identity.state())
    elif work == "leave":
        plan = plan_leave(identity.state())
    else:
        plan = plan_return_from_leave(identity.state())
    if not plan:
        return None

    run = pending_offboarding if work == "offboarding" else None
    return run_workflow(session, identity, work, plan, clock, rng, initiated_by, run=run)


def _workflow_history(session: Session) -> dict[int, dict]:
    """What has already happened for each employee, to decide which workflows are due.

    - offboarded: an offboarding workflow has started
    - pending_offboarding: a queued offboarding run waiting for the termination date
    - last_leave_type: the most recent of leave / return_from_leave
    """
    history: dict[int, dict] = {}
    runs = session.scalars(select(WorkflowRun).order_by(WorkflowRun.requested_at, WorkflowRun.id))
    for run in runs:
        entry = history.setdefault(run.employee_id, {})
        if run.workflow_type == "offboarding":
            if run.status == "pending":
                entry["pending_offboarding"] = run
            else:
                entry["offboarded"] = True
        elif run.workflow_type in ("leave", "return_from_leave"):
            entry["last_leave_type"] = run.workflow_type
    return history
