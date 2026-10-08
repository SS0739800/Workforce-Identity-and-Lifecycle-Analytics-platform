"""Which actions each lifecycle workflow performs, and in what order.

The plans are built from the current identity state, so re-running a workflow only
repeats the work that is still outstanding.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.lifecycle.reference import Entitlements


@dataclass(frozen=True)
class PlannedAction:
    action_type: str
    target: str | None = None


@dataclass(frozen=True)
class IdentityState:
    account_status: str | None  # None when no account exists
    groups: tuple[str, ...]
    roles: tuple[str, ...]
    licenses: tuple[str, ...]


def plan_onboarding(state: IdentityState, desired: Entitlements) -> list[PlannedAction]:
    # Every later step needs the account, so the executor stops if create_account fails.
    plan = []
    if state.account_status is None:
        plan.append(PlannedAction("create_account"))
    plan += [PlannedAction("add_group_membership", g) for g in desired.groups if g not in state.groups]
    plan += [PlannedAction("assign_role", r) for r in desired.roles if r not in state.roles]
    plan += [PlannedAction("assign_license", lic) for lic in desired.licenses if lic not in state.licenses]
    return plan


def plan_offboarding(state: IdentityState) -> list[PlannedAction]:
    # Disable first and revoke sessions straight away, so access stops before the
    # slower cleanup steps run. Cleanup continues even if an earlier step fails.
    plan = []
    if state.account_status is not None:
        plan.append(PlannedAction("disable_account"))
        plan.append(PlannedAction("revoke_session"))
        plan.append(PlannedAction("reset_password"))
    plan += [PlannedAction("remove_group_membership", g) for g in state.groups]
    plan += [PlannedAction("remove_role", r) for r in state.roles]
    plan += [PlannedAction("remove_license", lic) for lic in state.licenses]
    return plan


def plan_leave(state: IdentityState) -> list[PlannedAction]:
    # Access is suspended, not removed: groups, roles and licenses stay so they can be
    # restored on return. The leave flag records why the account is disabled.
    if state.account_status is None:
        return []
    return [
        PlannedAction("disable_account"),
        PlannedAction("revoke_session"),
        PlannedAction("update_attribute", "leave_status"),
    ]


def plan_return_from_leave(state: IdentityState) -> list[PlannedAction]:
    if state.account_status is None:
        return []
    return [
        PlannedAction("enable_account"),
        PlannedAction("update_attribute", "leave_status"),
    ]


# Actions that the rest of the workflow depends on. If one fails, later actions are skipped.
BLOCKING_ACTIONS = {"create_account"}

# Access actions: which kind of assignment they touch, and whether they add or remove it.
ASSIGNMENT_ACTIONS = {
    "add_group_membership": ("group", True),
    "remove_group_membership": ("group", False),
    "assign_role": ("role", True),
    "remove_role": ("role", False),
    "assign_license": ("license", True),
    "remove_license": ("license", False),
}


def _current(state: IdentityState, kind: str) -> tuple[str, ...]:
    return {"group": state.groups, "role": state.roles, "license": state.licenses}[kind]


def access_changes(state: IdentityState, desired: Entitlements) -> list[tuple[str, str, bool]]:
    """(kind, name, adding) changes that bring current access in line with birthright access.

    Used by the sync after a department, site or employment-type change.
    """
    changes = []
    for kind, wanted in (("group", desired.groups), ("role", desired.roles), ("license", desired.licenses)):
        current = _current(state, kind)
        changes += [(kind, name, True) for name in wanted if name not in current]
        changes += [(kind, name, False) for name in current if name not in wanted]
    return changes


def username_from_email(email: str, is_taken: Callable[[str], bool]) -> str:
    """Directory username: the email's local part, with a number added if it is already taken."""
    base = email.split("@")[0]
    username, suffix = base, 2
    while is_taken(username):
        username = f"{base}{suffix}"
        suffix += 1
    return username


# --- re-running a failed workflow ---------------------------------------------------------

def can_rerun(workflow_type: str, employment_status: str, leave_status: str) -> bool:
    """A re-run only makes sense while the situation that started the workflow still holds."""
    if workflow_type == "offboarding":
        return employment_status == "terminated"
    if employment_status != "active":
        return False
    if workflow_type == "leave":
        return leave_status == "on_leave"
    if workflow_type == "return_from_leave":
        return leave_status == "none"
    return True


def still_needed(state: IdentityState, action: PlannedAction) -> bool:
    """False when someone has already done what the action was meant to do."""
    action_type = action.action_type
    if action_type == "create_account":
        return state.account_status is None
    if action_type == "enable_account":
        return state.account_status == "disabled"
    if action_type == "disable_account":
        return state.account_status == "active"
    if action_type in ASSIGNMENT_ACTIONS:
        kind, adding = ASSIGNMENT_ACTIONS[action_type]
        assigned = action.target in _current(state, kind)
        return not assigned if adding else assigned
    return True


def plan_rerun(
    workflow_type: str,
    failed_actions: list[PlannedAction],
    state: IdentityState,
    desired: Entitlements,
) -> list[PlannedAction]:
    """Outstanding work for a re-run: retry the failed steps that still need doing.

    Onboarding is planned again from scratch, because a failed create_account means
    the later steps never ran.
    """
    if workflow_type == "onboarding":
        return plan_onboarding(state, desired)
    return [action for action in failed_actions if still_needed(state, action)]
