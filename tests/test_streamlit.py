"""Render each Streamlit page with Streamlit's test runner.

API calls go to the real FastAPI app (via TestClient) over the test database, inside a
transaction that is rolled back afterwards. The AI client is disabled, so no model is called.
"""

import pytest
import streamlit as st
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app.api.deps import get_ai_client
from app.core.config import PROJECT_ROOT
from app.db.database import get_session
from app.main import app
from streamlit_app import api

PAGES = str(PROJECT_ROOT / "streamlit_app" / "pages" / "{}.py")


@pytest.fixture
def backend(db, monkeypatch):
    """Route the Streamlit app's HTTP calls to the FastAPI app in-process."""
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_ai_client] = lambda: None
    client = TestClient(app)

    def request(method, path, params=None, body=None):
        response = client.request(method, path, params=params, json=body)
        if response.status_code >= 400:
            raise api.ApiError(f"API returned {response.status_code}: {response.json().get('detail')}",
                               response.status_code)
        return response.json()

    monkeypatch.setattr(api, "_request", request)
    st.cache_data.clear()
    yield client
    app.dependency_overrides.clear()
    st.cache_data.clear()


def run_page(name: str, session_state: dict | None = None) -> AppTest:
    page = AppTest.from_file(PAGES.format(name), default_timeout=60)
    for key, value in (session_state or {}).items():
        page.session_state[key] = value
    page.run()
    return page


def metric(page: AppTest, label: str) -> str:
    return next(m.value for m in page.metric if m.label == label)


@pytest.mark.parametrize("name", ["overview", "employees", "synchronization", "lifecycle", "data_quality", "ai_insights"])
def test_every_page_renders_without_errors(backend, name):
    page = run_page(name)
    assert not page.exception
    assert page.title  # every page has a title


def test_overview_numbers_come_from_the_api(backend, dataset):
    page = run_page("overview")
    active = sum(e["employment_status"] == "active" for e in dataset["employees"])
    assert metric(page, "Active employees") == f"{active:,}"
    assert metric(page, "Pending workflows") == str(sum(r["status"] == "pending" for r in dataset["workflow_runs"]))


def test_investigating_a_terminated_employee_with_leftover_access(backend, dataset):
    leavers = backend.get("/api/analytics/offboarding").json()["access_remaining"]
    employee_id = leavers[0]["employee_db_id"]
    page = run_page("employees", {"employee_id": employee_id})
    assert not page.exception
    assert metric(page, "Employment").startswith("terminated")
    assert any("Terminated, but" in item.value for item in list(page.warning) + list(page.error))
    assert [tab.label.split(" (")[0] for tab in page.tabs] == [
        "Profile", "Access", "Workflows", "Changes", "Data quality", "Activity"]


def test_unknown_employee_shows_an_error(backend):
    page = run_page("employees", {"employee_id": 999_999})
    assert any("404" in item.value for item in page.error)


def test_api_unreachable_is_reported_not_crashed(monkeypatch):
    def down(*args, **kwargs):
        raise api.ApiError("Can't reach the API at http://127.0.0.1:8000. Is it running?")

    monkeypatch.setattr(api, "_request", down)
    st.cache_data.clear()
    page = run_page("overview")
    assert not page.exception
    assert "Can't reach the API" in page.error[0].value
    st.cache_data.clear()


def test_sync_needs_confirmation_then_runs(backend):
    page = run_page("synchronization")
    run_button = next(b for b in page.button if b.label == "Run sync")
    assert run_button.disabled
    page.checkbox[0].check().run()
    next(b for b in page.button if b.label == "Run sync").click().run()
    assert not page.exception
    assert any("SYNC-" in item.value for item in page.success)


def test_ai_page_works_without_a_model(backend):
    page = run_page("ai_insights")
    next(b for b in page.button if b.label == "Ask").click().run()
    assert any("Type a question" in item.value for item in page.warning)

    page.text_input[0].input("Which departments had the most synchronization failures this quarter?")
    next(b for b in page.button if b.label == "Ask").click().run()
    assert not page.exception
    assert any("AI not configured" in item.value for item in page.info)
