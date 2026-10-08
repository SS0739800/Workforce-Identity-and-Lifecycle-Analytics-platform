from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.schemas.employee import (
    ActivityEvent,
    AttributeChangeOut,
    EmployeeDetail,
    EmployeeList,
    EmployeeSummary,
)
from app.schemas.workflow import WorkflowRunOut
from app.services import employee_service

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


@router.get("/{employee_db_id}", response_model=EmployeeDetail)
def get_employee(employee_db_id: int, session: Session = Depends(get_session)):
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
