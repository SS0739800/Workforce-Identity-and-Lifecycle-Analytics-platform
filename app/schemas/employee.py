from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EmployeeSummary(ORMModel):
    id: int
    employee_id: str | None
    first_name: str
    last_name: str
    email: str | None
    department: str | None
    job_title: str | None
    location: str | None
    employment_type: str
    employment_status: str
    leave_status: str
    hire_date: date
    termination_date: date | None


class EmployeeList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EmployeeSummary]


class ManagerRef(BaseModel):
    id: int
    employee_id: str | None
    name: str
    employment_status: str


class IdentityAccountOut(ORMModel):
    username: str
    account_status: str
    account_created_at: datetime
    account_disabled_at: datetime | None
    last_sync_at: datetime | None


class AccessAssignment(BaseModel):
    name: str
    status: str
    assigned_at: datetime
    removed_at: datetime | None


class DataQualityIssueOut(ORMModel):
    id: int
    issue_type: str
    field_name: str
    severity: str
    description: str
    detected_at: datetime
    resolved_at: datetime | None
    status: str


class EmployeeDetail(EmployeeSummary):
    manager: ManagerRef | None
    created_at: datetime
    updated_at: datetime
    identity_account: IdentityAccountOut | None
    groups: list[AccessAssignment]
    roles: list[AccessAssignment]
    licenses: list[AccessAssignment]
    data_quality_issues: list[DataQualityIssueOut]


class ActivityEvent(BaseModel):
    timestamp: datetime
    category: Literal["audit", "sync", "data_quality"]
    event_type: str
    description: str
    source: str


class AttributeChangeOut(ORMModel):
    id: int
    attribute_name: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime
    source: str
