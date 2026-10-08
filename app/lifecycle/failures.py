"""Controlled failure model for simulated identity operations.

Rates are assumptions chosen to produce believable, explainable patterns, not
measurements from any real environment. See docs/data-generation.md.
"""

import random
from dataclasses import dataclass

from app.lifecycle.reference import PRIVILEGED_ROLE


@dataclass(frozen=True)
class FailureMode:
    error_type: str
    weight: float
    message: str


@dataclass(frozen=True)
class FailureProfile:
    rate: float
    modes: tuple[FailureMode, ...]


TIMEOUT_MESSAGE = "Request timed out after 60 seconds"

ACTION_FAILURE_PROFILES: dict[str, FailureProfile] = {
    "create_account": FailureProfile(0.03, (
        FailureMode("DEPENDENCY_ERROR", 0.5, "Directory service rejected the account creation request"),
        FailureMode("TIMEOUT", 0.3, TIMEOUT_MESSAGE),
        FailureMode("PERMISSION_ERROR", 0.2, "Service account cannot create accounts in the target container"),
    )),
    "enable_account": FailureProfile(0.02, (
        FailureMode("TIMEOUT", 0.5, TIMEOUT_MESSAGE),
        FailureMode("RESOURCE_NOT_FOUND", 0.5, "Account not found in directory"),
    )),
    "disable_account": FailureProfile(0.02, (
        FailureMode("TIMEOUT", 0.6, TIMEOUT_MESSAGE),
        FailureMode("RESOURCE_NOT_FOUND", 0.4, "Account not found in directory"),
    )),
    "reset_password": FailureProfile(0.02, (
        FailureMode("VALIDATION_ERROR", 0.5, "Generated password rejected by the directory password policy"),
        FailureMode("TIMEOUT", 0.5, TIMEOUT_MESSAGE),
    )),
    "update_attribute": FailureProfile(0.01, (
        FailureMode("VALIDATION_ERROR", 1.0, "Directory rejected the value for '{target}'"),
    )),
    "add_group_membership": FailureProfile(0.01, (
        FailureMode("RESOURCE_NOT_FOUND", 0.7, "Group '{target}' not found"),
        FailureMode("TIMEOUT", 0.3, TIMEOUT_MESSAGE),
    )),
    "remove_group_membership": FailureProfile(0.025, (
        FailureMode("TIMEOUT", 0.5, TIMEOUT_MESSAGE),
        FailureMode("PERMISSION_ERROR", 0.3, "Service account cannot modify membership of '{target}'"),
        FailureMode("RESOURCE_NOT_FOUND", 0.2, "Group '{target}' not found"),
    )),
    "assign_role": FailureProfile(0.015, (
        FailureMode("PERMISSION_ERROR", 1.0, "Service account cannot assign role '{target}'"),
    )),
    "remove_role": FailureProfile(0.03, (
        FailureMode("PERMISSION_ERROR", 0.7, "Service account cannot remove role '{target}'"),
        FailureMode("TIMEOUT", 0.3, TIMEOUT_MESSAGE),
    )),
    "assign_license": FailureProfile(0.03, (
        FailureMode("DEPENDENCY_ERROR", 0.6, "Licensing service returned an error for '{target}'"),
        FailureMode("TIMEOUT", 0.4, TIMEOUT_MESSAGE),
    )),
    # License removal goes through a separate, rate-limited licensing API, so it is
    # assumed to be the least reliable cleanup step.
    "remove_license": FailureProfile(0.08, (
        FailureMode("DEPENDENCY_ERROR", 0.55, "Licensing service throttled the request (HTTP 429)"),
        FailureMode("TIMEOUT", 0.45, TIMEOUT_MESSAGE),
    )),
    "revoke_session": FailureProfile(0.05, (
        FailureMode("TIMEOUT", 0.7, TIMEOUT_MESSAGE),
        FailureMode("DEPENDENCY_ERROR", 0.3, "Token service unavailable"),
    )),
}

# Removing a privileged role needs elevated rights the automation account often lacks.
PRIVILEGED_ROLE_REMOVAL_MULTIPLIER = 3.0
# During a license shortage, assignments fail far more often for a single, specific reason.
LICENSE_SHORTAGE_FAILURE_RATE = 0.35
SYNC_RECORD_TIMEOUT_RATE = 0.01


def roll_action_failure(
    rng: random.Random,
    action_type: str,
    target: str | None,
    license_shortage: bool = False,
) -> tuple[str, str] | None:
    """Return (error_type, error_message) if the action fails, otherwise None."""
    if action_type == "assign_license" and license_shortage:
        if rng.random() < LICENSE_SHORTAGE_FAILURE_RATE:
            return "DEPENDENCY_ERROR", f"No available '{target}' licenses in the pool"

    profile = ACTION_FAILURE_PROFILES[action_type]
    rate = profile.rate
    if action_type == "remove_role" and target == PRIVILEGED_ROLE:
        rate *= PRIVILEGED_ROLE_REMOVAL_MULTIPLIER

    if rng.random() >= rate:
        return None

    mode = rng.choices(profile.modes, weights=[m.weight for m in profile.modes])[0]
    return mode.error_type, mode.message.format(target=target)


def roll_sync_timeout(rng: random.Random) -> bool:
    return rng.random() < SYNC_RECORD_TIMEOUT_RATE


def action_duration_seconds(rng: random.Random, action_type: str, error_type: str | None) -> int:
    if error_type == "TIMEOUT":
        return 60
    if error_type is not None:
        return rng.randint(1, 5)
    if action_type == "create_account":
        return rng.randint(8, 25)
    return rng.randint(1, 8)
