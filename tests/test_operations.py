"""Lifecycle operations against PostgreSQL: HR changes -> sync -> workflows -> data-quality scan.

Every test runs inside a transaction that is rolled back afterwards. Times are after the
simulated year, as if the platform kept running.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.lifecycle.reference import access_for_employee
from app.lifecycle.sync import MAX_SYNC_ATTEMPTS
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
from app.services import data_quality_service, hr_service, sync_service, workflow_service
from app.services.identity_store import employee_record
from tests.helpers import ACCOUNT_CREATION_FAILS, ALWAYS_FAIL, NEVER_FAIL, FixedRandom

NOW = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)


# --- helpers ------------------------------------------------------------------------------

def run_sync(db, when=NOW, failure=NEVER_FAIL):
    return sync_service.run_sync(db, when, FixedRandom(failure))


def settle(db, when=NOW - timedelta(days=1)):
    """Process anything left over from the generated data, so tests only see their own changes."""
    run_sync(db, when)


def clean_employee(db, department="Production") -> Employee:
    """An active, non-manager employee with an account, no leave, and no data-quality issues."""
    open_issue = select(DataQualityIssue.employee_id).where(DataQualityIssue.status == "open")
    return db.scalars(
        select(Employee)
        .join(IdentityAccount, IdentityAccount.employee_id == Employee.id)
        .where(
            Employee.department == department,
            Employee.employment_status == "active",
            Employee.leave_status == "none",
            Employee.termination_date.is_(None),
            Employee.job_title.like("%Operator%"),
            IdentityAccount.account_status == "active",
            Employee.id.not_in(open_issue),
        )
        .order_by(Employee.id)
    ).first()


def a_manager(db, department="Engineering") -> Employee:
    return db.scalars(
        select(Employee).where(
            Employee.department == department,
            Employee.job_title == "Engineering Manager",
            Employee.employment_status == "active",
        )
    ).first()


def account_of(db, employee) -> IdentityAccount | None:
    return db.scalar(select(IdentityAccount).where(IdentityAccount.employee_id == employee.id))


def active(db, model, employee) -> set[str]:
    name_column = {GroupMembership: "group_name", RoleAssignment: "role_name", LicenseAssignment: "license_name"}[model]
    rows = db.scalars(select(model).where(model.employee_id == employee.id, model.status == "active"))
    return {getattr(row, name_column) for row in rows}


def results_for(db, sync_run, employee) -> list[SyncRecordResult]:
    return list(db.scalars(select(SyncRecordResult).where(
        SyncRecordResult.sync_run_id == sync_run.id, SyncRecordResult.employee_id == employee.id
    )))


def workflows_for(db, employee, workflow_type) -> list[WorkflowRun]:
    """Workflows of one type requested during the test (the generated history is ignored)."""
    return list(db.scalars(
        select(WorkflowRun)
        .where(
            WorkflowRun.employee_id == employee.id,
            WorkflowRun.workflow_type == workflow_type,
            WorkflowRun.requested_at >= NOW - timedelta(days=1),
        )
        .order_by(WorkflowRun.requested_at, WorkflowRun.id)
    ))


def open_issue_types(db, employee) -> set[str]:
    rows = db.scalars(select(DataQualityIssue).where(
        DataQualityIssue.employee_id == employee.id, DataQualityIssue.status == "open"
    ))
    return {issue.issue_type for issue in rows}


def new_hire(db, **overrides) -> Employee:
    values = {
        "first_name": "Morgan",
        "last_name": "Testhire",
        "department": "Engineering",
        "job_title": "Process Engineer",
        "manager_id": a_manager(db).id,
        "location": "Dayton Plant",
        "employment_type": "full_time",
        "hire_date": date(2026, 10, 19),
    }
    values.update(overrides)
    return hr_service.create_employee(db, values, NOW - timedelta(hours=12))


# --- onboarding ------------------------------------------------------------------------------

def test_new_hire_is_onboarded_by_the_next_sync(db):
    hire = new_hire(db)
    outcome = run_sync(db)

    [result] = results_for(db, outcome.run, hire)
    assert result.status == "success"
    account = account_of(db, hire)
    assert (account.username, account.account_status) == ("morgan.testhire", "active")

    desired = access_for_employee(employee_record(hire))
    assert active(db, GroupMembership, hire) == set(desired.groups)
    assert active(db, RoleAssignment, hire) == set(desired.roles)
    assert active(db, LicenseAssignment, hire) == set(desired.licenses)

    [onboarding] = workflows_for(db, hire, "onboarding")
    assert onboarding.status == "completed"
    assert onboarding.initiated_by == "manual_sync"
    assert onboarding in outcome.workflows_started


def test_failed_account_creation_leaves_no_access_until_rerun(db):
    hire = new_hire(db)
    run_sync(db, failure=ACCOUNT_CREATION_FAILS)
    [onboarding] = workflows_for(db, hire, "onboarding")
    actions = db.scalars(select(WorkflowAction).where(WorkflowAction.workflow_run_id == onboarding.id)).all()
    assert onboarding.status == "failed"
    assert actions[0].action_type == "create_account" and actions[0].status == "failed"
    assert all(a.status == "skipped" for a in actions[1:])
    assert account_of(db, hire) is None

    # The sync does not retry onboarding by itself; the service desk re-runs it.
    run_sync(db, NOW + timedelta(days=1))
    assert len(workflows_for(db, hire, "onboarding")) == 1
    rerun = workflow_service.rerun_workflow(db, onboarding.id, NOW + timedelta(days=1, hours=8), FixedRandom(NEVER_FAIL))
    assert (rerun.status, rerun.initiated_by) == ("completed", "service_desk")
    assert account_of(db, hire).account_status == "active"


def test_hire_with_missing_manager_is_held_then_onboarded_after_fix(db):
    settle(db)
    hire = new_hire(db, manager_id=None)

    for day in range(MAX_SYNC_ATTEMPTS):
        outcome = run_sync(db, NOW + timedelta(days=day))
        [result] = results_for(db, outcome.run, hire)
        assert (result.status, result.error_type) == ("failed", "MISSING_ATTRIBUTE")

    held = run_sync(db, NOW + timedelta(days=MAX_SYNC_ATTEMPTS))
    assert results_for(db, held.run, hire) == []  # retry limit reached
    assert account_of(db, hire) is None

    hr_service.update_employee(db, hire.id, {"manager_id": a_manager(db).id}, NOW + timedelta(days=4, hours=10))
    fixed = run_sync(db, NOW + timedelta(days=5))
    [result] = results_for(db, fixed.run, hire)
    assert result.status == "success"
    assert account_of(db, hire).account_status == "active"


def test_duplicate_hr_record_is_never_onboarded(db):
    original = new_hire(db)
    duplicate = new_hire(db, email=original.email)
    outcome = run_sync(db)
    assert results_for(db, outcome.run, original)[0].status == "success"
    [result] = results_for(db, outcome.run, duplicate)
    assert (result.status, result.error_type) == ("failed", "VALIDATION_ERROR")
    assert account_of(db, duplicate) is None


# --- attribute sync -------------------------------------------------------------------------------

def test_transfer_updates_birthright_access(db):
    settle(db)
    person = clean_employee(db)
    assert "DEPT-PROD" in active(db, GroupMembership, person)

    hr_service.update_employee(
        db, person.id, {"department": "Engineering", "job_title": "Process Engineer"}, NOW - timedelta(hours=8)
    )
    outcome = run_sync(db)

    [result] = results_for(db, outcome.run, person)
    assert result.status == "success"
    groups = active(db, GroupMembership, person)
    assert "DEPT-ENG" in groups and "DEPT-PROD" not in groups
    assert active(db, RoleAssignment, person) == {"PLM Engineer"}
    assert "CAD Workstation" in active(db, LicenseAssignment, person)
    assert account_of(db, person).last_sync_at == result.completed_at

    changes = db.scalars(select(AttributeChangeLog).where(
        AttributeChangeLog.employee_id == person.id, AttributeChangeLog.changed_at == NOW - timedelta(hours=8)
    )).all()
    assert {c.attribute_name for c in changes} == {"department", "job_title"}


def test_unchanged_records_are_skipped(db):
    settle(db)
    person = clean_employee(db)
    hr_service.update_employee(db, person.id, {"location": "Greenville Plant"}, NOW - timedelta(hours=8))
    first = run_sync(db)
    second = run_sync(db, NOW + timedelta(days=1))
    assert len(results_for(db, first.run, person)) == 1
    assert results_for(db, second.run, person) == []
    assert second.run.total_records == second.run.successful_records + second.run.failed_records + second.run.skipped_records


# --- offboarding ------------------------------------------------------------------------------------

def terminate(db, person, effective: date, when: datetime):
    hr_service.update_employee(
        db, person.id, {"employment_status": "terminated", "termination_date": effective}, when
    )


def test_termination_offboards_and_removes_all_access(db):
    settle(db)
    person = clean_employee(db)
    terminate(db, person, NOW.date() - timedelta(days=1), NOW - timedelta(hours=10))
    outcome = run_sync(db)

    [offboarding] = workflows_for(db, person, "offboarding")
    assert offboarding.status == "completed"
    assert offboarding in outcome.workflows_started
    assert account_of(db, person).account_status == "disabled"
    assert active(db, GroupMembership, person) == set()
    assert active(db, RoleAssignment, person) == set()
    assert active(db, LicenseAssignment, person) == set()

    events = {e.event_type for e in db.scalars(select(AuditEvent).where(AuditEvent.employee_id == person.id))}
    assert {"account_disabled", "sessions_revoked", "password_reset", "group_removed", "license_removed"} <= events

    data_quality_service.run_scan(db, NOW + timedelta(days=1))
    assert open_issue_types(db, person) == set()


def test_failed_offboarding_is_detected_then_fixed_by_rerun(db):
    settle(db)
    person = clean_employee(db)
    terminate(db, person, NOW.date() - timedelta(days=1), NOW - timedelta(hours=10))
    run_sync(db, failure=ALWAYS_FAIL)

    [offboarding] = workflows_for(db, person, "offboarding")
    assert offboarding.status == "failed"
    assert account_of(db, person).account_status == "active"

    data_quality_service.run_scan(db, NOW + timedelta(hours=16))
    assert {
        "active_account_for_terminated_employee",
        "stale_group_membership",
        "stale_role_assignment",
        "license_on_inactive_employee",
    } <= open_issue_types(db, person)

    rerun = workflow_service.rerun_workflow(db, offboarding.id, NOW + timedelta(days=1), FixedRandom(NEVER_FAIL))
    assert rerun.status == "completed"
    assert account_of(db, person).account_status == "disabled"
    assert active(db, GroupMembership, person) == set()

    result = data_quality_service.run_scan(db, NOW + timedelta(days=1, hours=16))
    assert open_issue_types(db, person) == set()
    assert result.issues_resolved >= 4


def test_future_dated_termination_waits_as_pending(db):
    settle(db)
    person = clean_employee(db)
    effective = NOW.date() + timedelta(days=10)
    hr_service.update_employee(db, person.id, {"termination_date": effective}, NOW - timedelta(hours=8))
    run_sync(db)

    [queued] = workflows_for(db, person, "offboarding")
    assert (queued.status, queued.started_at) == ("pending", None)
    assert account_of(db, person).account_status == "active"

    # Running again before the date does not queue a second workflow.
    run_sync(db, NOW + timedelta(days=1))
    assert len(workflows_for(db, person, "offboarding")) == 1

    later = NOW + timedelta(days=11)
    hr_service.update_employee(db, person.id, {"employment_status": "terminated"}, later - timedelta(hours=1))
    run_sync(db, later)
    [offboarding] = workflows_for(db, person, "offboarding")
    assert offboarding.id == queued.id
    assert offboarding.status == "completed"
    assert offboarding.requested_at < offboarding.started_at


# --- leave and return --------------------------------------------------------------------------

def test_leave_suspends_access_and_return_restores_it(db):
    settle(db)
    person = clean_employee(db)
    groups_before = active(db, GroupMembership, person)

    hr_service.update_employee(db, person.id, {"leave_status": "on_leave"}, NOW - timedelta(hours=8))
    run_sync(db)
    [leave] = workflows_for(db, person, "leave")
    assert leave.status == "completed"
    assert account_of(db, person).account_status == "disabled"
    assert active(db, GroupMembership, person) == groups_before  # access kept for the return

    back = NOW + timedelta(days=30)
    hr_service.update_employee(db, person.id, {"leave_status": "none"}, back - timedelta(hours=8))
    run_sync(db, back)
    [returned] = workflows_for(db, person, "return_from_leave")
    assert returned.status == "completed"
    assert account_of(db, person).account_status == "active"


def test_leave_rerun_is_refused_after_the_employee_returns(db):
    settle(db)
    person = clean_employee(db)
    hr_service.update_employee(db, person.id, {"leave_status": "on_leave"}, NOW - timedelta(hours=8))
    run_sync(db, failure=ALWAYS_FAIL)
    [leave] = workflows_for(db, person, "leave")
    assert leave.status == "failed"

    hr_service.update_employee(db, person.id, {"leave_status": "none"}, NOW + timedelta(days=2))
    with pytest.raises(workflow_service.RerunNotAllowed):
        workflow_service.rerun_workflow(db, leave.id, NOW + timedelta(days=3), FixedRandom(NEVER_FAIL))


def test_completed_workflow_cannot_be_rerun(db):
    completed = db.scalars(select(WorkflowRun).where(WorkflowRun.status == "completed")).first()
    with pytest.raises(workflow_service.RerunNotAllowed):
        workflow_service.rerun_workflow(db, completed.id, NOW, FixedRandom(NEVER_FAIL))
    with pytest.raises(workflow_service.WorkflowNotFound):
        workflow_service.rerun_workflow(db, 999_999, NOW, FixedRandom(NEVER_FAIL))


# --- data quality and HR input ---------------------------------------------------------------------

def test_scan_detects_and_resolves_an_hr_error(db):
    person = clean_employee(db)
    good_email = person.email
    hr_service.update_employee(db, person.id, {"email": "not-an-email"}, NOW)
    data_quality_service.run_scan(db, NOW + timedelta(hours=1))
    assert open_issue_types(db, person) == {"invalid_email"}

    hr_service.update_employee(db, person.id, {"email": good_email}, NOW + timedelta(days=1))
    data_quality_service.run_scan(db, NOW + timedelta(days=1, hours=1))
    assert open_issue_types(db, person) == set()


def test_invalid_hr_changes_are_rejected(db):
    person = clean_employee(db)
    with pytest.raises(hr_service.InvalidHRChange):
        hr_service.update_employee(db, person.id, {"salary": 1}, NOW)
    with pytest.raises(hr_service.InvalidHRChange):
        hr_service.update_employee(db, person.id, {"manager_id": 999_999}, NOW)
    with pytest.raises(hr_service.InvalidHRChange):
        hr_service.update_employee(db, person.id, {"manager_id": person.id}, NOW)


def test_new_hires_get_the_next_employee_id_and_a_unique_email(db):
    first = new_hire(db)
    second = new_hire(db)
    assert int(second.employee_id[3:]) == int(first.employee_id[3:]) + 1
    assert first.email == "morgan.testhire@northstar-mfg.example"
    assert second.email == "morgan.testhire2@northstar-mfg.example"


def test_runs_started_in_the_same_second_get_distinct_ids(db):
    first = run_sync(db).run
    second = run_sync(db).run
    assert first.run_id == f"SYNC-{NOW:%Y%m%d-%H%M%S}"
    assert second.run_id == f"{first.run_id}-2"


def test_only_one_sync_runs_at_a_time(db, loaded_engine):
    with loaded_engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:key)"), {"key": sync_service.SYNC_LOCK_KEY})
        try:
            with pytest.raises(sync_service.SyncAlreadyRunning):
                run_sync(db)
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": sync_service.SYNC_LOCK_KEY})
