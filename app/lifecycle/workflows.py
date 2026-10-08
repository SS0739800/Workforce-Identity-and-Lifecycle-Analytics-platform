"""Which actions each lifecycle workflow performs, and in what order.

The plans are built from the current identity state, so re-running a workflow only
repeats the work that is still outstanding.
"""

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
