"""HTTP tests for the operations endpoints. Each test's changes are rolled back."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_now, get_rng
from app.db.database import get_session
from app.main import app
from tests.helpers import NEVER_FAIL, FixedRandom

NOW = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)


@pytest.fixture
def client(db):
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_now] = lambda: NOW
    app.dependency_overrides[get_rng] = lambda: FixedRandom(NEVER_FAIL)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def manager_id(client) -> int:
    params = {"department": "Engineering", "employment_status": "active", "limit": 200}
    body = client.get("/api/employees", params=params).json()
    return next(e["id"] for e in body["items"] if e["job_title"] == "Engineering Manager")


def hire(client, **overrides) -> dict:
    payload = {
        "first_name": "Riley",
        "last_name": "Apitest",
        "hire_date": "2026-10-19",
        "department": "Engineering",
        "job_title": "Process Engineer",
        "location": "Chicago Office",
        "manager_id": manager_id(client),
    }
    payload.update(overrides)
    return client.post("/api/employees", json=payload)


def test_hire_sync_and_inspect_workflow(client):
    response = hire(client)
    assert response.status_code == 201
    employee = response.json()
    assert employee["employee_id"].startswith("EMP")
    assert employee["identity_account"] is None

    sync = client.post("/api/sync/runs")
    assert sync.status_code == 201
    body = sync.json()
    assert body["run"]["triggered_by"] == "manual"
    onboarding = next(w for w in body["workflows_started"] if w["employee_id"] == employee["id"])
    assert (onboarding["workflow_type"], onboarding["status"]) == ("onboarding", "completed")

    detail = client.get(f"/api/sync/runs/{body['run']['id']}").json()
    assert any(r["employee_id"] == employee["id"] and r["status"] == "success" for r in detail["results"])

    workflow = client.get(f"/api/workflows/{onboarding['id']}").json()
    assert workflow["actions"][0]["action_type"] == "create_account"

    after = client.get(f"/api/employees/{employee['id']}").json()
    assert after["identity_account"]["account_status"] == "active"
    assert {g["name"] for g in after["groups"]} >= {"All Staff", "DEPT-ENG"}


def test_newest_sync_run_is_listed_first(client):
    created = client.post("/api/sync/runs").json()["run"]
    runs = client.get("/api/sync/runs", params={"limit": 5}).json()
    assert runs[0]["id"] == created["id"]


def test_patch_logs_changes(client):
    employee = hire(client).json()
    response = client.patch(f"/api/employees/{employee['id']}", json={"location": "Remote"})
    assert response.status_code == 200
    assert response.json()["location"] == "Remote"
    changes = client.get(f"/api/employees/{employee['id']}/changes").json()
    assert changes[0]["attribute_name"] == "location"
    assert (changes[0]["old_value"], changes[0]["new_value"]) == ("Chicago Office", "Remote")


@pytest.mark.parametrize("payload", [
    {"salary": 100},                        # not an HR attribute this API manages
    {"employment_status": "retired"},       # not an allowed status
    {"leave_status": "sabbatical"},
    {"manager_id": 999999},                 # manager does not exist
    {"termination_date": "next week"},
])
def test_invalid_patch_is_rejected(client, payload):
    employee = hire(client).json()
    assert client.patch(f"/api/employees/{employee['id']}", json=payload).status_code == 422


def test_hr_data_is_accepted_even_when_wrong(client):
    """Bad department values are stored; the sync and the data-quality scan catch them."""
    response = hire(client, department="Logisitcs")
    assert response.status_code == 201
    assert response.json()["department"] == "Logisitcs"

    scan = client.post("/api/data-quality/scans")
    assert scan.status_code == 201
    issues = client.get(f"/api/employees/{response.json()['id']}").json()["data_quality_issues"]
    assert "invalid_department" in {i["issue_type"] for i in issues}


def test_missing_required_fields_are_rejected(client):
    assert client.post("/api/employees", json={"first_name": "Only"}).status_code == 422


def test_rerun_of_completed_workflow_conflicts(client):
    employee = hire(client).json()
    started = client.post("/api/sync/runs").json()["workflows_started"]
    onboarding = next(w for w in started if w["employee_id"] == employee["id"])
    response = client.post(f"/api/workflows/{onboarding['id']}/rerun")
    assert response.status_code == 409
    assert "only failed workflows" in response.json()["detail"]


@pytest.mark.parametrize("method, path", [
    ("get", "/api/workflows/999999"),
    ("post", "/api/workflows/999999/rerun"),
    ("get", "/api/sync/runs/999999"),
    ("patch", "/api/employees/999999"),
])
def test_unknown_ids_return_404(client, method, path):
    kwargs = {"json": {}} if method == "patch" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 404
