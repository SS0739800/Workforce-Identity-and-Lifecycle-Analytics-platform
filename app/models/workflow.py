from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.lifecycle.reference import (
    ACTION_STATUSES,
    ACTION_TYPES,
    ERROR_TYPES,
    WORKFLOW_STATUSES,
    WORKFLOW_TYPES,
)
from app.models._constraints import allowed_values


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        allowed_values("workflow_type", WORKFLOW_TYPES),
        allowed_values("status", WORKFLOW_STATUSES),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    workflow_type: Mapped[str] = mapped_column(String(30))
    # When the workflow was queued. A future-dated termination queues an offboarding
    # workflow days before it starts, so queue time and run time are tracked separately.
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    initiated_by: Mapped[str] = mapped_column(String(50))


class WorkflowAction(Base):
    __tablename__ = "workflow_actions"
    __table_args__ = (
        allowed_values("action_type", ACTION_TYPES),
        allowed_values("status", ACTION_STATUSES),
        allowed_values("error_type", ERROR_TYPES),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(40))
    # The group, role, license or attribute the action applies to (NULL for account-level actions).
    target_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
