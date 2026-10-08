from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.lifecycle.reference import ERROR_TYPES, SYNC_RECORD_STATUSES, SYNC_RUN_STATUSES
from app.models._constraints import allowed_values


class SyncRun(Base):
    """One execution of the HR -> identity attribute sync.

    total_records = successful_records + failed_records + skipped_records.
    Skipped records needed no update (unchanged, terminated, or held after repeated
    failures), so only successful and failed records get a sync_record_results row.
    """

    __tablename__ = "sync_runs"
    __table_args__ = (allowed_values("status", SYNC_RUN_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    total_records: Mapped[int]
    successful_records: Mapped[int]
    failed_records: Mapped[int]
    skipped_records: Mapped[int]
    triggered_by: Mapped[str] = mapped_column(String(50))
    # Set when the whole run fails before any record is processed (e.g. the HR export is missing).
    error_message: Mapped[str | None] = mapped_column(Text)


class SyncRecordResult(Base):
    __tablename__ = "sync_record_results"
    __table_args__ = (
        allowed_values("status", SYNC_RECORD_STATUSES),
        allowed_values("error_type", ERROR_TYPES),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    error_type: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
