from app.lifecycle.reference import entitlements_for
from app.lifecycle.workflows import (
    IdentityState,
    plan_leave,
    plan_offboarding,
    plan_onboarding,
    plan_return_from_leave,
)

NO_ACCOUNT = IdentityState(account_status=None, groups=(), roles=(), licenses=())
ACTIVE = IdentityState(
    account_status="active",
    groups=("All Staff", "DEPT-ENG"),
    roles=("PLM Engineer",),
    licenses=("Office Suite Standard", "CAD Workstation"),
)


def action_types(plan) -> list[str]:
    return [action.action_type for action in plan]


def test_onboarding_creates_account_then_grants_birthright_access():
    desired = entitlements_for("Engineering", "Dayton Plant", "Process Engineer", "full_time", is_manager=False)
    plan = plan_onboarding(NO_ACCOUNT, desired)
    assert plan[0].action_type == "create_account"
    assert {a.target for a in plan if a.action_type == "add_group_membership"} == set(desired.groups)
    assert {a.target for a in plan if a.action_type == "assign_role"} == set(desired.roles)
    assert {a.target for a in plan if a.action_type == "assign_license"} == set(desired.licenses)


def test_onboarding_rerun_only_grants_what_is_missing():
    desired = entitlements_for("Engineering", "Dayton Plant", "Process Engineer", "full_time", is_manager=False)
    plan = plan_onboarding(ACTIVE, desired)
    assert "create_account" not in action_types(plan)
    assert all(a.target not in ACTIVE.groups for a in plan if a.action_type == "add_group_membership")


def test_offboarding_disables_first_and_removes_all_access():
    plan = plan_offboarding(ACTIVE)
    assert action_types(plan)[:3] == ["disable_account", "revoke_session", "reset_password"]
    assert {a.target for a in plan if a.action_type == "remove_group_membership"} == set(ACTIVE.groups)
    assert {a.target for a in plan if a.action_type == "remove_role"} == set(ACTIVE.roles)
    assert {a.target for a in plan if a.action_type == "remove_license"} == set(ACTIVE.licenses)


def test_leave_suspends_without_removing_access():
    plan = plan_leave(ACTIVE)
    assert action_types(plan) == ["disable_account", "revoke_session", "update_attribute"]


def test_return_from_leave_re_enables_account():
    assert action_types(plan_return_from_leave(ACTIVE)) == ["enable_account", "update_attribute"]


def test_no_account_means_nothing_to_suspend():
    assert plan_leave(NO_ACCOUNT) == []
    assert plan_return_from_leave(NO_ACCOUNT) == []


def test_privileged_titles_get_directory_admin_role():
    access = entitlements_for("Information Technology", "Chicago Office", "Systems Administrator", "full_time", False)
    assert "Directory Administrator" in access.roles
