from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    total_records: int
    successful_records: int
    failed_records: int
    skipped_records: int
    triggered_by: str
    error_message: str | None


class SyncRecordResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: int
    status: str
    error_type: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime


class SyncRunDetail(SyncRunOut):
    results: list[SyncRecordResultOut]


class StartedWorkflow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    workflow_type: str
    status: str


class SyncRunCreated(BaseModel):
    run: SyncRunOut
    workflows_started: list[StartedWorkflow]


class ScanResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scanned_at: datetime
    employees_scanned: int
    issues_opened: int
    issues_resolved: int
    open_issues: int
