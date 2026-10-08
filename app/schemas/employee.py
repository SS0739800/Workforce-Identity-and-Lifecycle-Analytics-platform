from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


EmploymentType = Literal["full_time", "part_time", "intern", "contractor"]


class EmployeeCreate(BaseModel):
    """A new hire entered in HR. Department, title, location and manager are not checked
    against reference data on purpose: the sync and the data-quality scan catch bad values."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    hire_date: date
    employment_type: EmploymentType = "full_time"
    department: str | None = Field(None, max_length=100)
    job_title: str | None = Field(None, max_length=100)
    manager_id: int | None = None
    location: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=255, description="Generated from the name if omitted")
    employee_id: str | None = Field(None, max_length=20, description="Next EMP number if omitted")


class EmployeeUpdate(BaseModel):
    """HR attribute changes. Only the fields sent are changed; each change is logged."""

    model_config = ConfigDict(extra="forbid")

    employee_id: str | None = Field(None, max_length=20)
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: str | None = Field(None, max_length=255)
    department: str | None = Field(None, max_length=100)
    job_title: str | None = Field(None, max_length=100)
    manager_id: int | None = None
    location: str | None = Field(None, max_length=100)
    employment_type: EmploymentType | None = None
    termination_date: date | None = None
    employment_status: Literal["active", "terminated"] | None = None
    leave_status: Literal["none", "on_leave"] | None = None


class AttributeChangeOut(ORMModel):
    id: int
    attribute_name: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime
    source: str
