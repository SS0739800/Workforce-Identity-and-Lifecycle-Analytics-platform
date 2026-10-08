from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.lifecycle.reference import EMPLOYMENT_STATUSES, EMPLOYMENT_TYPES, LEAVE_STATUSES
from app.models._constraints import allowed_values


class Employee(Base):
    """HR record for a synthetic employee: the source data the identity sync reads.

    Department, location, email and similar fields are deliberately unconstrained.
    Source HR data can contain bad values, and detecting them is the job of the
    data-quality checks, not the database.
    """

    __tablename__ = "employees"
    __table_args__ = (
        allowed_values("employment_status", EMPLOYMENT_STATUSES),
        allowed_values("leave_status", LEAVE_STATUSES),
        allowed_values("employment_type", EMPLOYMENT_TYPES),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # HR business identifier (EMP00001). Nullable because a missing ID is one of the
    # data-quality problems the platform has to detect.
    employee_id: Mapped[str | None] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(100))
    job_title: Mapped[str | None] = mapped_column(String(100))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    location: Mapped[str | None] = mapped_column(String(100))
    employment_type: Mapped[str] = mapped_column(String(20))
    hire_date: Mapped[date] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(String(20))
    leave_status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
