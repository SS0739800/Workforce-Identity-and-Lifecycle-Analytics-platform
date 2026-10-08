"""Simulated identity-system records. These are PostgreSQL rows, not AWS IAM users."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.lifecycle.reference import ACCOUNT_STATUSES, ASSIGNMENT_STATUSES
from app.models._constraints import allowed_values


class IdentityAccount(Base):
    __tablename__ = "identity_accounts"
    __table_args__ = (allowed_values("account_status", ACCOUNT_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # In every child table, employee_id references employees.id (the surrogate key),
    # not the HR business identifier, which can be missing or duplicated.
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), unique=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    account_status: Mapped[str] = mapped_column(String(20))
    account_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    account_disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (allowed_values("status", ASSIGNMENT_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    group_name: Mapped[str] = mapped_column(String(100))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (allowed_values("status", ASSIGNMENT_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    role_name: Mapped[str] = mapped_column(String(100))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))


class LicenseAssignment(Base):
    __tablename__ = "license_assignments"
    __table_args__ = (allowed_values("status", ASSIGNMENT_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    license_name: Mapped[str] = mapped_column(String(100))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
