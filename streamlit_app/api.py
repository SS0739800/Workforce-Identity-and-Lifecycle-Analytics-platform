"""Calls to the FastAPI backend. The Streamlit app never reads the database directly.

GET responses are cached for a minute. Any POST (sync, scan, re-run, AI) clears the cache,
so the next page view shows the new state.
"""

import os
from datetime import date

import httpx
import streamlit as st

BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
# AI requests can take several seconds; everything else is fast.
TIMEOUT_SECONDS = 90


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _request(method: str, path: str, params: dict | None = None, body: dict | None = None):
    try:
        response = httpx.request(method, BASE_URL + path, params=params, json=body, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        raise ApiError(f"Can't reach the API at {BASE_URL}. Is it running? ({type(error).__name__})") from error
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(f"API returned {response.status_code}: {detail}", response.status_code)
    return response.json()


@st.cache_data(ttl=60, show_spinner=False)
def _cached_get(path: str, params: tuple) -> dict | list:
    return _request("GET", path, dict(params))


def get(path: str, **params) -> dict | list:
    clean = tuple(sorted((key, str(value)) for key, value in params.items() if value is not None))
    return _cached_get(path, clean)


def post(path: str, body: dict | None = None, **params) -> dict:
    result = _request("POST", path, {k: v for k, v in params.items() if v is not None}, body)
    st.cache_data.clear()
    return result


# --- named calls ------------------------------------------------------------------------------

def analytics(endpoint: str, start: date | None = None, end: date | None = None, **extra) -> dict:
    return get(f"/api/analytics/{endpoint}", start_date=start, end_date=end, **extra)


def employees(search: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    return get("/api/employees", search=search or None, employment_status=status, limit=limit, offset=offset)


def employee(employee_db_id: int) -> dict:
    return get(f"/api/employees/{employee_db_id}")


def employee_section(employee_db_id: int, section: str) -> list:
    return get(f"/api/employees/{employee_db_id}/{section}")


def workflow(workflow_run_id: int) -> dict:
    return get(f"/api/workflows/{workflow_run_id}")
