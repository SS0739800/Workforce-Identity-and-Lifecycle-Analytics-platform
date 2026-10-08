from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.lifecycle.reference import DQ_SEVERITIES, DQ_STATUSES
from app.models._constraints import allowed_values


class AttributeChangeLog(Base):
    """A change to an HR attribute, as recorded by the source system."""

    __tablename__ = "attribute_change_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    attribute_name: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[str | None] = mapped_column(String(255))
    new_value: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(50))


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (
        allowed_values("severity", DQ_SEVERITIES),
        allowed_values("status", DQ_STATUSES),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    issue_type: Mapped[str] = mapped_column(String(50))
    field_name: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))


class AuditEvent(Base):
    """Identity-side audit trail: account, access and session changes."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(50))
