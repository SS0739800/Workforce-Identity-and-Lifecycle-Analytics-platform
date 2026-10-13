import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import ai, analytics, employees, operations
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import get_session
from app.services.ai_service import IncidentNotApplicable
from app.services.analytics_service import InvalidDateRange
from app.services.employee_service import EmployeeNotFound
from app.services.hr_service import InvalidHRChange
from app.services.sync_service import SyncAlreadyRunning
from app.services.workflow_service import RerunNotAllowed, WorkflowNotFound

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    logger.info("API starting")
    yield
    logger.info("API stopping")


app = FastAPI(
    title="Workforce Identity & Lifecycle Analytics API",
    description="API over synthetic identity operations data: investigation, analytics and simulated lifecycle operations.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(employees.router)
app.include_router(analytics.router)
app.include_router(operations.router)
app.include_router(ai.router)


@app.get("/health", tags=["health"])
def health(session: Session = Depends(get_session)):
    """Liveness check used by the deployment: the API is up and can reach the database."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check: database unreachable")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})
    return {"status": "ok", "database": "ok"}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


@app.exception_handler(EmployeeNotFound)
async def employee_not_found(request: Request, error: EmployeeNotFound):
    return _error(404, f"Employee {error.args[0]} not found")


@app.exception_handler(WorkflowNotFound)
async def workflow_not_found(request: Request, error: WorkflowNotFound):
    return _error(404, f"Workflow {error.args[0]} not found")


@app.exception_handler(InvalidDateRange)
async def invalid_date_range(request: Request, error: InvalidDateRange):
    return _error(422, str(error))


@app.exception_handler(InvalidHRChange)
async def invalid_hr_change(request: Request, error: InvalidHRChange):
    return _error(422, str(error))


@app.exception_handler(RerunNotAllowed)
async def rerun_not_allowed(request: Request, error: RerunNotAllowed):
    return _error(409, str(error))


@app.exception_handler(SyncAlreadyRunning)
async def sync_already_running(request: Request, error: SyncAlreadyRunning):
    return _error(409, str(error))


@app.exception_handler(IncidentNotApplicable)
async def incident_not_applicable(request: Request, error: IncidentNotApplicable):
    return _error(409, str(error))
