from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_now
from app.db.database import get_session
from app.schemas.employee import (
    ActivityEvent,
    AttributeChangeOut,
    EmployeeCreate,
    EmployeeDetail,
    EmployeeList,
    EmployeeSummary,
    EmployeeUpdate,
)
from app.schemas.workflow import WorkflowRunOut
from app.services import employee_service, hr_service

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("", response_model=EmployeeList)
def list_employees(
    search: str | None = Query(None, max_length=100, description="Matches HR employee ID, name or email"),
    department: str | None = Query(None, max_length=100),
    employment_status: Literal["active", "terminated"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    total, employees = employee_service.list_employees(
        session, search, department, employment_status, limit, offset
    )
    return EmployeeList(
        total=total,
        limit=limit,
        offset=offset,
        items=[EmployeeSummary.model_validate(e) for e in employees],
    )


@router.post("", response_model=EmployeeDetail, status_code=status.HTTP_201_CREATED)
def create_employee(
    body: EmployeeCreate,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    """Enter a new hire in the simulated HR system. The next sync starts onboarding."""
    employee = hr_service.create_employee(session, body.model_dump(), now)
    session.commit()
    return employee_service.get_employee_detail(session, employee.id)


@router.get("/{employee_db_id}", response_model=EmployeeDetail)
def get_employee(employee_db_id: int, session: Session = Depends(get_session)):
    return employee_service.get_employee_detail(session, employee_db_id)


@router.patch("/{employee_db_id}", response_model=EmployeeDetail)
def update_employee(
    employee_db_id: int,
    body: EmployeeUpdate,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    """Change HR attributes. Transfers, terminations and leave take effect at the next sync."""
    hr_service.update_employee(session, employee_db_id, body.model_dump(exclude_unset=True), now)
    session.commit()
    return employee_service.get_employee_detail(session, employee_db_id)


@router.get("/{employee_db_id}/activity", response_model=list[ActivityEvent])
def get_activity(
    employee_db_id: int,
    limit: int = Query(200, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    return employee_service.get_activity(session, employee_db_id, limit)


@router.get("/{employee_db_id}/workflows", response_model=list[WorkflowRunOut])
def get_workflows(employee_db_id: int, session: Session = Depends(get_session)):
    return employee_service.get_workflows(session, employee_db_id)


@router.get("/{employee_db_id}/changes", response_model=list[AttributeChangeOut])
def get_changes(employee_db_id: int, session: Session = Depends(get_session)):
    return employee_service.get_changes(session, employee_db_id)
