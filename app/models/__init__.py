"""Import every model so Base.metadata is complete for Alembic and the loader."""

from app.models.activity import AttributeChangeLog, AuditEvent, DataQualityIssue
from app.models.ai import AIInsightRun
from app.models.employee import Employee
from app.models.identity import GroupMembership, IdentityAccount, LicenseAssignment, RoleAssignment
from app.models.sync import SyncRecordResult, SyncRun
from app.models.workflow import WorkflowAction, WorkflowRun

__all__ = [
    "AIInsightRun",
    "AttributeChangeLog",
    "AuditEvent",
    "DataQualityIssue",
    "Employee",
    "GroupMembership",
    "IdentityAccount",
    "LicenseAssignment",
    "RoleAssignment",
    "SyncRecordResult",
    "SyncRun",
    "WorkflowAction",
    "WorkflowRun",
]
