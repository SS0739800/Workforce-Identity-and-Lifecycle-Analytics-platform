from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorkflowActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action_type: str
    target_name: str | None
    status: str
    started_at: datetime
    completed_at: datetime
    error_type: str | None
    error_message: str | None


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_type: str
    status: str
    initiated_by: str
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    actions: list[WorkflowActionOut]
