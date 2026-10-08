"""Runs a workflow's planned actions and reports what happened to each one.

The executor doesn't know where identity data lives. The synthetic-data simulator passes an
in-memory store and the API passes one backed by PostgreSQL, so both follow the same rules
for failures, skips and blocked steps.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.lifecycle import failures
from app.lifecycle.workflows import BLOCKING_ACTIONS, PlannedAction


class IdentityStore(Protocol):
    """The identity data for one employee, as the executor needs to see it."""

    def account_status(self) -> str | None:
        """'active', 'disabled', or None when no account exists."""

    def apply(self, action: PlannedAction, when: datetime) -> None:
        """Make the change a successful action describes (create account, remove group, ...)."""


@dataclass(frozen=True)
class ActionOutcome:
    action: PlannedAction
    status: str  # success, failed or skipped
    started_at: datetime
    completed_at: datetime
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class WorkflowResult:
    outcomes: list[ActionOutcome]
    finished_at: datetime

    @property
    def status(self) -> str:
        return "failed" if self.failed_actions else "completed"

    @property
    def failed_actions(self) -> list[PlannedAction]:
        return [o.action for o in self.outcomes if o.status == "failed"]


def execute_plan(
    plan: list[PlannedAction],
    store: IdentityStore,
    start: datetime,
    rng: random.Random,
    license_shortage: bool = False,
) -> WorkflowResult:
    """Attempt each action in order. Durations are simulated, so timestamps advance accordingly."""
    clock = start
    blocked_by: str | None = None
    outcomes: list[ActionOutcome] = []

    for action in plan:
        if blocked_by:
            outcome = ActionOutcome(
                action, "skipped", clock, clock, error_message=f"Not attempted because {blocked_by} failed"
            )
        else:
            outcome = _attempt(action, store, clock, rng, license_shortage)
        outcomes.append(outcome)
        clock = outcome.completed_at + timedelta(seconds=rng.randint(0, 2))

        if outcome.status == "failed" and action.action_type in BLOCKING_ACTIONS:
            blocked_by = action.action_type

    return WorkflowResult(outcomes, clock)


def _attempt(
    action: PlannedAction,
    store: IdentityStore,
    when: datetime,
    rng: random.Random,
    license_shortage: bool,
) -> ActionOutcome:
    action_type = action.action_type
    account_status = store.account_status()

    # Nothing to do: record it, as the original automation logged "Account was already disabled".
    if action_type == "disable_account" and account_status == "disabled":
        return ActionOutcome(action, "skipped", when, when + timedelta(seconds=1),
                             "ALREADY_DISABLED", "Account was already disabled")
    if action_type == "enable_account" and account_status == "active":
        return ActionOutcome(action, "skipped", when, when + timedelta(seconds=1),
                             error_message="Account was already enabled")

    failure = failures.roll_action_failure(rng, action_type, action.target, license_shortage=license_shortage)
    error_type = failure[0] if failure else None
    finished = when + timedelta(seconds=failures.action_duration_seconds(rng, action_type, error_type))
    if failure:
        return ActionOutcome(action, "failed", when, finished, failure[0], failure[1])

    store.apply(action, finished)
    return ActionOutcome(action, "success", when, finished)
