"""Unit tests for the shared lifecycle engine used by both the simulator and the API."""

from datetime import date, datetime, timezone

from app.lifecycle.executor import execute_plan
from app.lifecycle.reference import Entitlements
from app.lifecycle.sync import MAX_SYNC_ATTEMPTS, due_workflows, needs_attribute_sync, sync_record_error
from app.lifecycle.validation import AccessSnapshot, find_issues, issue_changes
from app.lifecycle.workflows import (
    IdentityState,
    PlannedAction,
    access_changes,
    can_rerun,
    plan_offboarding,
    plan_rerun,
    username_from_email,
)
from tests.helpers import ALWAYS_FAIL, NEVER_FAIL, FixedRandom
from tests.test_validation import employee

START = datetime(2026, 3, 10, 2, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, account_status: str | None):
        self.status = account_status
        self.applied: list[PlannedAction] = []

    def account_status(self) -> str | None:
        return self.status

    def apply(self, action: PlannedAction, when: datetime) -> None:
        self.applied.append(action)
        if action.action_type == "create_account":
            self.status = "active"
        elif action.action_type == "disable_account":
            self.status = "disabled"


ONBOARDING = [
    PlannedAction("create_account"),
    PlannedAction("add_group_membership", "All Staff"),
    PlannedAction("assign_license", "Office Suite Standard"),
]


# --- executor ---------------------------------------------------------------------------

def test_successful_plan_applies_every_action_in_order():
    store = FakeStore(None)
    result = execute_plan(ONBOARDING, store, START, FixedRandom(NEVER_FAIL))
    assert result.status == "completed"
    assert store.applied == ONBOARDING
    assert [o.status for o in result.outcomes] == ["success"] * 3
    times = [o.started_at for o in result.outcomes]
    assert times == sorted(times)
    assert result.finished_at >= result.outcomes[-1].completed_at


def test_failed_create_account_skips_the_rest():
    store = FakeStore(None)
    result = execute_plan(ONBOARDING, store, START, FixedRandom(ALWAYS_FAIL))
    assert result.status == "failed"
    assert [o.status for o in result.outcomes] == ["failed", "skipped", "skipped"]
    assert result.outcomes[0].error_type is not None
    assert result.outcomes[1].error_message == "Not attempted because create_account failed"
    assert result.failed_actions == [ONBOARDING[0]]
    assert store.applied == []


def test_offboarding_keeps_going_after_a_failure():
    state = IdentityState("active", ("All Staff", "VPN Users"), ("PLM Engineer",), ("CAD Workstation",))
    plan = plan_offboarding(state)
    result = execute_plan(plan, FakeStore("active"), START, FixedRandom(ALWAYS_FAIL))
    assert all(o.status == "failed" for o in result.outcomes)
    assert result.failed_actions == plan


def test_disabling_a_disabled_account_is_skipped_not_failed():
    store = FakeStore("disabled")
    result = execute_plan([PlannedAction("disable_account")], store, START, FixedRandom(ALWAYS_FAIL))
    outcome = result.outcomes[0]
    assert (outcome.status, outcome.error_type) == ("skipped", "ALREADY_DISABLED")
    assert result.status == "completed"
    assert store.applied == []


def test_license_shortage_has_its_own_error():
    plan = [PlannedAction("assign_license", "CAD Workstation")]
    result = execute_plan(plan, FakeStore("active"), START, FixedRandom(ALWAYS_FAIL), license_shortage=True)
    assert result.outcomes[0].error_message == "No available 'CAD Workstation' licenses in the pool"


def test_timeouts_take_sixty_seconds():
    plan = [PlannedAction("revoke_session")]
    rng = FixedRandom(ALWAYS_FAIL)
    rng.choices = lambda population, weights: [population[0]]  # pick the first mode: TIMEOUT
    outcome = execute_plan(plan, FakeStore("active"), START, rng).outcomes[0]
    assert outcome.error_type == "TIMEOUT"
    assert (outcome.completed_at - outcome.started_at).total_seconds() == 60


# --- sync rules -------------------------------------------------------------------------------

def test_needs_attribute_sync():
    def needs(**overrides):
        args = dict(employment_status="active", has_account=True, onboarding_started=True,
                    changed_since_last_sync=True, failed_attempts=0)
        args.update(overrides)
        return needs_attribute_sync(**args)

    assert needs()
    assert not needs(changed_since_last_sync=False)
    assert not needs(employment_status="terminated")
    assert not needs(failed_attempts=MAX_SYNC_ATTEMPTS)
    assert needs(has_account=False, onboarding_started=False)
    assert not needs(has_account=False, onboarding_started=True)


def test_sync_record_error_order_of_checks():
    rng = FixedRandom(NEVER_FAIL)
    assert sync_record_error(employee(), date(2026, 1, 1), None, False, rng) is None
    assert sync_record_error(employee(manager_id=None), date(2026, 1, 1), None, False, rng)[0] == "MISSING_ATTRIBUTE"
    assert sync_record_error(employee(), date(2026, 1, 1), None, True, rng)[0] == "RESOURCE_NOT_FOUND"
    assert sync_record_error(employee(), date(2026, 1, 1), 3, False, rng)[0] == "VALIDATION_ERROR"
    assert sync_record_error(employee(), date(2026, 1, 1), None, False, FixedRandom(ALWAYS_FAIL))[0] == "TIMEOUT"


def test_due_workflows():
    today = date(2026, 3, 10)

    def due(record, **flags):
        args = dict(has_account=True, already_offboarded=False, has_pending_offboarding=False, leave_applied=False)
        args.update(flags)
        return due_workflows(record, today=today, **args)

    assert due(employee()) == []
    assert due(employee(employment_status="terminated")) == ["offboarding"]
    assert due(employee(employment_status="terminated"), already_offboarded=True) == []
    assert due(employee(termination_date=date(2026, 3, 20))) == ["queue_offboarding"]
    assert due(employee(termination_date=date(2026, 3, 20)), has_pending_offboarding=True) == []
    assert due(employee(leave_status="on_leave")) == ["leave"]
    assert due(employee(leave_status="on_leave"), leave_applied=True) == []
    assert due(employee(), leave_applied=True) == ["return_from_leave"]


# --- re-runs and access ----------------------------------------------------------------------

def test_can_rerun():
    assert can_rerun("offboarding", "terminated", "none")
    assert not can_rerun("offboarding", "active", "none")
    assert not can_rerun("onboarding", "terminated", "none")
    assert can_rerun("leave", "active", "on_leave")
    assert not can_rerun("leave", "active", "none")
    assert can_rerun("return_from_leave", "active", "none")


def test_rerun_only_retries_what_is_still_outstanding():
    # The license was removed by hand after the first attempt; the group is still assigned.
    state = IdentityState("disabled", ("VPN Users",), (), ())
    failed = [
        PlannedAction("remove_group_membership", "VPN Users"),
        PlannedAction("remove_license", "CAD Workstation"),
        PlannedAction("disable_account"),
        PlannedAction("revoke_session"),
    ]
    plan = plan_rerun("offboarding", failed, state, Entitlements((), (), ()))
    assert plan == [PlannedAction("remove_group_membership", "VPN Users"), PlannedAction("revoke_session")]


def test_onboarding_rerun_is_planned_from_scratch():
    desired = Entitlements(("All Staff",), ("PLM Engineer",), ("Office Suite Standard",))
    plan = plan_rerun("onboarding", [], IdentityState(None, (), (), ()), desired)
    assert [a.action_type for a in plan] == ["create_account", "add_group_membership", "assign_role", "assign_license"]


def test_access_changes_after_a_transfer():
    state = IdentityState("active", ("All Staff", "DEPT-PROD"), ("MES Line Operator",), ("Office Suite Frontline",))
    desired = Entitlements(("All Staff", "DEPT-ENG"), ("PLM Engineer",), ("Office Suite Frontline",))
    assert access_changes(state, desired) == [
        ("group", "DEPT-ENG", True),
        ("group", "DEPT-PROD", False),
        ("role", "PLM Engineer", True),
        ("role", "MES Line Operator", False),
    ]


def test_username_from_email():
    taken = {"alex.smith", "alex.smith2"}
    assert username_from_email("alex.smith@northstar-mfg.example", taken.__contains__) == "alex.smith3"
    assert username_from_email("jo.lee@northstar-mfg.example", taken.__contains__) == "jo.lee"


# --- data-quality scan --------------------------------------------------------------------------

def test_find_issues_and_issue_changes():
    now = datetime(2026, 1, 15, 18, tzinfo=timezone.utc)
    records = [
        employee(id=1),
        employee(id=2, first_name="Jo", manager_id=None),
        employee(id=3, first_name="Sam", employment_status="terminated", termination_date=date(2026, 1, 2)),
    ]
    access = {1: AccessSnapshot("active", 3, 1, 1), 3: AccessSnapshot("disabled", 1, 0, 0)}
    found = find_issues(records, access, now)
    assert set(found) == {(2, "missing_manager"), (2, "missing_identity_account"), (3, "stale_group_membership")}

    to_open, to_resolve = issue_changes([(2, "missing_manager"), (1, "invalid_email")], found)
    assert set(to_open) == {(2, "missing_identity_account"), (3, "stale_group_membership")}
    assert to_resolve == [(1, "invalid_email")]
