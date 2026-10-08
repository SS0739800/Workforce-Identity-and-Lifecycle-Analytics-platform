"""PostgreSQL-backed identity data for one employee.

Implements the executor's IdentityStore so lifecycle workflows run against the database
with the same rules the simulator uses. Changes are added to the session; the caller commits.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lifecycle.workflows import ASSIGNMENT_ACTIONS, IdentityState, PlannedAction, username_from_email
from app.models import AuditEvent, Employee, GroupMembership, IdentityAccount, LicenseAssignment, RoleAssignment

# kind -> (model, name column)
ASSIGNMENT_MODELS = {
    "group": (GroupMembership, "group_name"),
    "role": (RoleAssignment, "role_name"),
    "license": (LicenseAssignment, "license_name"),
}


def employee_record(employee: Employee) -> dict:
    """The HR record as a plain dict, the shape the shared validation and sync rules expect."""
    return {column.name: getattr(employee, column.name) for column in Employee.__table__.columns}


class DatabaseIdentity:
    def __init__(self, session: Session, employee: Employee):
        self.session = session
        self.employee = employee
        self.account = session.scalar(select(IdentityAccount).where(IdentityAccount.employee_id == employee.id))

    # -- IdentityStore -------------------------------------------------------------------

    def account_status(self) -> str | None:
        return self.account.account_status if self.account else None

    def apply(self, action: PlannedAction, when: datetime) -> None:
        action_type = action.action_type
        source = "workflow_engine"

        if action_type in ASSIGNMENT_ACTIONS:
            kind, adding = ASSIGNMENT_ACTIONS[action_type]
            if adding:
                self.assign(kind, action.target, when, source)
            else:
                self.unassign(kind, action.target, when, source)
        elif action_type == "create_account":
            username = username_from_email(self.employee.email, is_taken=self._username_taken)
            self.account = IdentityAccount(
                employee_id=self.employee.id,
                username=username,
                account_status="active",
                account_created_at=when,
                last_sync_at=when,
            )
            self.session.add(self.account)
            self.audit("account_created", f"Account '{username}' created", when, source)
        elif action_type == "enable_account":
            self.account.account_status = "active"
            self.account.account_disabled_at = None
            self.audit("account_enabled", "Account enabled", when, source)
        elif action_type == "disable_account":
            self.account.account_status = "disabled"
            self.account.account_disabled_at = when
            self.audit("account_disabled", "Account disabled", when, source)
        elif action_type == "reset_password":
            # Only the fact of the reset is recorded. No password is generated or stored.
            self.audit("password_reset", "Password reset to a random value", when, source)
        elif action_type == "update_attribute":
            self.audit("attribute_updated", f"Directory attribute '{action.target}' updated", when, source)
        elif action_type == "revoke_session":
            self.audit("sessions_revoked", "All sign-in sessions revoked", when, source)

    # -- helpers ----------------------------------------------------------------------------

    def state(self) -> IdentityState:
        return IdentityState(
            account_status=self.account_status(),
            groups=tuple(self._active("group")),
            roles=tuple(self._active("role")),
            licenses=tuple(self._active("license")),
        )

    def assign(self, kind: str, name: str, when: datetime, source: str) -> None:
        model, name_column = ASSIGNMENT_MODELS[kind]
        self.session.add(model(employee_id=self.employee.id, **{name_column: name}, assigned_at=when, status="active"))
        self.audit(f"{kind}_assigned", f"{kind.capitalize()} '{name}' assigned", when, source)

    def unassign(self, kind: str, name: str, when: datetime, source: str) -> None:
        row = self._active(kind)[name]
        row.status = "removed"
        row.removed_at = when
        self.audit(f"{kind}_removed", f"{kind.capitalize()} '{name}' removed", when, source)

    def audit(self, event_type: str, description: str, when: datetime, source: str) -> None:
        self.session.add(AuditEvent(
            employee_id=self.employee.id,
            event_type=event_type,
            description=description,
            event_timestamp=when,
            source=source,
        ))

    def _active(self, kind: str) -> dict:
        """Active assignments of one kind, by name, in the order they were assigned."""
        model, name_column = ASSIGNMENT_MODELS[kind]
        self.session.flush()
        rows = self.session.scalars(
            select(model)
            .where(model.employee_id == self.employee.id, model.status == "active")
            .order_by(model.assigned_at, model.id)
        )
        return {getattr(row, name_column): row for row in rows}

    def _username_taken(self, username: str) -> bool:
        return self.session.scalar(select(IdentityAccount.id).where(IdentityAccount.username == username)) is not None
