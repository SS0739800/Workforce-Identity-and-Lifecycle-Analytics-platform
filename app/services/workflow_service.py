"""Run lifecycle workflows against the database and record every action."""

import logging
import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lifecycle.executor import execute_plan
from app.lifecycle.reference import access_for_employee
from app.lifecycle.workflows import PlannedAction, can_rerun, plan_rerun
from app.models import Employee, WorkflowAction, WorkflowRun
from app.services.identity_store import DatabaseIdentity, employee_record

logger = logging.getLogger(__name__)


class WorkflowNotFound(Exception):
    pass


class RerunNotAllowed(Exception):
    """The workflow can't be re-run (not failed, situation changed, or nothing left to do)."""


def run_workflow(
    session: Session,
    identity: DatabaseIdentity,
    workflow_type: str,
    plan: list[PlannedAction],
    now: datetime,
    rng: random.Random,
    initiated_by: str,
    run: WorkflowRun | None = None,
) -> WorkflowRun:
    """Execute a plan and store the workflow run with one row per action.

    `run` is passed when a queued (pending) workflow is being started.
    """
    if run is None:
        run = WorkflowRun(
            employee_id=identity.employee.id,
            workflow_type=workflow_type,
            requested_at=now,
            status="pending",
            initiated_by=initiated_by,
        )
        session.add(run)
        session.flush()

    run.started_at = now
    result = execute_plan(plan, identity, now, rng)
    for outcome in result.outcomes:
        session.add(WorkflowAction(
            workflow_run_id=run.id,
            action_type=outcome.action.action_type,
            target_name=outcome.action.target,
            status=outcome.status,
            started_at=outcome.started_at,
            completed_at=outcome.completed_at,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
        ))
    run.completed_at = result.finished_at
    run.status = result.status
    session.flush()

    logger.info(
        "Workflow %s %s for employee %s: %s (%d actions, %d failed)",
        run.id, workflow_type, identity.employee.id, run.status, len(result.outcomes), len(result.failed_actions),
    )
    return run


def get_workflow(session: Session, workflow_run_id: int) -> WorkflowRun:
    run = session.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise WorkflowNotFound(workflow_run_id)
    return run


def get_actions(session: Session, workflow_run_id: int) -> list[WorkflowAction]:
    return list(session.scalars(
        select(WorkflowAction)
        .where(WorkflowAction.workflow_run_id == workflow_run_id)
        .order_by(WorkflowAction.started_at, WorkflowAction.id)
    ))


def rerun_workflow(session: Session, workflow_run_id: int, now: datetime, rng: random.Random) -> WorkflowRun:
    """Service-desk re-run: retry the steps of a failed workflow that are still outstanding."""
    previous = get_workflow(session, workflow_run_id)
    if previous.status != "failed":
        raise RerunNotAllowed(f"Workflow {previous.id} is {previous.status}; only failed workflows can be re-run")

    employee = session.get(Employee, previous.employee_id)
    if not can_rerun(previous.workflow_type, employee.employment_status, employee.leave_status):
        raise RerunNotAllowed(
            f"Employee {employee.id} is {employee.employment_status} with leave status {employee.leave_status}; "
            f"a {previous.workflow_type} re-run no longer applies"
        )

    failed = [
        PlannedAction(action.action_type, action.target_name)
        for action in get_actions(session, previous.id)
        if action.status == "failed"
    ]
    identity = DatabaseIdentity(session, employee)
    plan = plan_rerun(previous.workflow_type, failed, identity.state(), access_for_employee(employee_record(employee)))
    if not plan:
        raise RerunNotAllowed(f"Nothing outstanding for workflow {previous.id}; the failed steps were already done")

    return run_workflow(session, identity, previous.workflow_type, plan, now, rng, initiated_by="service_desk")
