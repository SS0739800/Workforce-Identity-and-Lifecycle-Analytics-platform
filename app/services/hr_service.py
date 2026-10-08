"""Simulated HR system: create employee records and change HR attributes.

These endpoints stand in for the HR system that feeds the sync. They deliberately accept
values the sync will reject (an unknown department, a blank manager) because bad source data
is part of what the platform has to detect. Only the fixed vocabularies enforced by the
database (statuses, employment type) are validated here.
"""

from datetime import date, datetime

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from app.lifecycle.reference import EMAIL_DOMAIN
from app.models import AttributeChangeLog, Employee
from app.services.employee_service import get_employee

# Attributes HR may change through the API.
EDITABLE_ATTRIBUTES = (
    "employee_id",
    "first_name",
    "last_name",
    "email",
    "department",
    "job_title",
    "manager_id",
    "location",
    "employment_type",
    "termination_date",
    "employment_status",
    "leave_status",
)


class InvalidHRChange(ValueError):
    pass


def _check_manager(session: Session, manager_id: int | None, employee_id: int | None = None) -> None:
    if manager_id is None:
        return
    if manager_id == employee_id:
        raise InvalidHRChange("An employee cannot be their own manager")
    if session.get(Employee, manager_id) is None:
        raise InvalidHRChange(f"Manager {manager_id} does not exist")


def _next_employee_id(session: Session) -> str:
    """EMP + the next number after the highest existing HR employee ID."""
    number = cast(func.substr(Employee.employee_id, 4), Integer)  # 'EMP00042' -> 42
    highest = session.scalar(select(func.max(number)).where(Employee.employee_id.like("EMP%")))
    return f"EMP{(highest or 0) + 1:05d}"


def _default_email(session: Session, first_name: str, last_name: str) -> str:
    base = f"{first_name}.{last_name}".lower().replace(" ", "")
    name, suffix = base, 2
    while session.scalar(select(Employee.id).where(Employee.email == f"{name}@{EMAIL_DOMAIN}")) is not None:
        name = f"{base}{suffix}"
        suffix += 1
    return f"{name}@{EMAIL_DOMAIN}"


def create_employee(session: Session, values: dict, now: datetime) -> Employee:
    """A new hire entered in HR. The next sync hands it to onboarding."""
    _check_manager(session, values.get("manager_id"))
    employee = Employee(
        employee_id=values.get("employee_id") or _next_employee_id(session),
        first_name=values["first_name"],
        last_name=values["last_name"],
        email=values.get("email") or _default_email(session, values["first_name"], values["last_name"]),
        department=values.get("department"),
        job_title=values.get("job_title"),
        manager_id=values.get("manager_id"),
        location=values.get("location"),
        employment_type=values["employment_type"],
        hire_date=values["hire_date"],
        termination_date=None,
        employment_status="active",
        leave_status="none",
        created_at=now,
        updated_at=now,
    )
    session.add(employee)
    session.flush()
    return employee


def update_employee(session: Session, employee_db_id: int, changes: dict, now: datetime) -> Employee:
    """Apply HR changes and log each changed attribute. Lifecycle work happens at the next sync."""
    employee = get_employee(session, employee_db_id)
    unknown = set(changes) - set(EDITABLE_ATTRIBUTES)
    if unknown:
        raise InvalidHRChange(f"Attributes cannot be changed: {', '.join(sorted(unknown))}")
    if "manager_id" in changes:
        _check_manager(session, changes["manager_id"], employee.id)

    for attribute in EDITABLE_ATTRIBUTES:
        if attribute not in changes:
            continue
        old, new = getattr(employee, attribute), changes[attribute]
        if old == new:
            continue
        setattr(employee, attribute, new)
        session.add(AttributeChangeLog(
            employee_id=employee.id,
            attribute_name=attribute,
            old_value=_as_text(old),
            new_value=_as_text(new),
            changed_at=now,
            source="hr_system",
        ))
        employee.updated_at = now
    session.flush()
    return employee


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
