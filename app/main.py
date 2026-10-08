import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import analytics, employees
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.analytics_service import InvalidDateRange
from app.services.employee_service import EmployeeNotFound

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    logger.info("API starting")
    yield
    logger.info("API stopping")


app = FastAPI(
    title="Workforce Identity & Lifecycle Analytics API",
    description="Read-only API over synthetic identity operations data.",
    version="0.2.0",
    lifespan=lifespan,
)
app.include_router(employees.router)
app.include_router(analytics.router)


@app.exception_handler(EmployeeNotFound)
async def employee_not_found(request: Request, error: EmployeeNotFound):
    return JSONResponse(status_code=404, content={"detail": f"Employee {error.args[0]} not found"})


@app.exception_handler(InvalidDateRange)
async def invalid_date_range(request: Request, error: InvalidDateRange):
    return JSONResponse(status_code=422, content={"detail": str(error)})
