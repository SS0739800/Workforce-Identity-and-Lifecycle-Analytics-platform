"""Operations endpoints: run the sync, run the data-quality scan, inspect and re-run workflows.

These change data. Each request runs in one transaction that is committed only if the whole
operation succeeds.
"""

import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_now, get_rng
from app.db.database import get_session
from app.models import SyncRecordResult, SyncRun
from app.schemas.sync import ScanResultOut, SyncRecordResultOut, SyncRunCreated, SyncRunDetail, SyncRunOut
from app.schemas.workflow import WorkflowActionOut, WorkflowRunOut
from app.services import data_quality_service, sync_service, workflow_service

router = APIRouter(prefix="/api", tags=["operations"])


@router.post("/sync/runs", response_model=SyncRunCreated, status_code=status.HTTP_201_CREATED)
def start_sync_run(
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
    rng: random.Random = Depends(get_rng),
):
    """Run the HR -> identity sync now, then start any lifecycle workflows it detects."""
    outcome = sync_service.run_sync(session, now, rng, triggered_by="manual")
    session.commit()
    return SyncRunCreated(
        run=SyncRunOut.model_validate(outcome.run),
        workflows_started=outcome.workflows_started,
    )


@router.get("/sync/runs", response_model=list[SyncRunOut])
def list_sync_runs(limit: int = Query(20, ge=1, le=200), session: Session = Depends(get_session)):
    return session.scalars(select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(limit)).all()


@router.get("/sync/runs/{sync_run_id}", response_model=SyncRunDetail)
def get_sync_run(sync_run_id: int, session: Session = Depends(get_session)):
    run = session.get(SyncRun, sync_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Sync run {sync_run_id} not found")
    results = session.scalars(
        select(SyncRecordResult).where(SyncRecordResult.sync_run_id == run.id).order_by(SyncRecordResult.id)
    )
    return SyncRunDetail(
        **SyncRunOut.model_validate(run).model_dump(),
        results=[SyncRecordResultOut.model_validate(r) for r in results],
    )


@router.post("/data-quality/scans", response_model=ScanResultOut, status_code=status.HTTP_201_CREATED)
def start_scan(session: Session = Depends(get_session), now: datetime = Depends(get_now)):
    """Re-check every record: open new data-quality issues and resolve fixed ones."""
    result = data_quality_service.run_scan(session, now)
    session.commit()
    return result


def _workflow_out(session: Session, run) -> WorkflowRunOut:
    actions = workflow_service.get_actions(session, run.id)
    return WorkflowRunOut(
        id=run.id,
        workflow_type=run.workflow_type,
        status=run.status,
        initiated_by=run.initiated_by,
        requested_at=run.requested_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        actions=[WorkflowActionOut.model_validate(a) for a in actions],
    )


@router.get("/workflows/{workflow_run_id}", response_model=WorkflowRunOut)
def get_workflow(workflow_run_id: int, session: Session = Depends(get_session)):
    return _workflow_out(session, workflow_service.get_workflow(session, workflow_run_id))


@router.post("/workflows/{workflow_run_id}/rerun", response_model=WorkflowRunOut, status_code=status.HTTP_201_CREATED)
def rerun_workflow(
    workflow_run_id: int,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
    rng: random.Random = Depends(get_rng),
):
    """Service-desk re-run of a failed workflow: retries the steps that are still outstanding."""
    run = workflow_service.rerun_workflow(session, workflow_run_id, now, rng)
    session.commit()
    return _workflow_out(session, run)
