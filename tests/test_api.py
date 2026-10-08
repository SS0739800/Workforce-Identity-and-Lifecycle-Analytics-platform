from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.main import app


@pytest.fixture(scope="module")
def client(loaded_engine):
    def test_session():
        with Session(loaded_engine) as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def employee_with(dataset, predicate) -> dict:
    return next(e for e in dataset["employees"] if predicate(e))


# --- employees --------------------------------------------------------------------------

def test_list_employees_paginates(client, dataset):
    response = client.get("/api/employees", params={"limit": 25, "offset": 50})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(dataset["employees"])
    assert len(body["items"]) == 25
    assert body["items"][0]["id"] == 51


def test_search_by_hr_employee_id(client):
    body = client.get("/api/employees", params={"search": "EMP00042"}).json()
    assert [item["employee_id"] for item in body["items"]] == ["EMP00042"]


def test_search_by_name_is_case_insensitive(client, dataset):
    person = dataset["employees"][100]
    full_name = f"{person['first_name']} {person['last_name']}".upper()
    body = client.get("/api/employees", params={"search": full_name}).json()
    assert person["id"] in {item["id"] for item in body["items"]}


def test_filter_by_status_and_department(client, dataset):
    expected = sum(
        e["employment_status"] == "terminated" and e["department"] == "Production" for e in dataset["employees"]
    )
    body = client.get(
        "/api/employees", params={"employment_status": "terminated", "department": "Production"}
    ).json()
    assert body["total"] == expected


@pytest.mark.parametrize("params", [
    {"limit": 0},
    {"limit": 201},
    {"offset": -1},
    {"employment_status": "retired"},
])
def test_invalid_list_parameters_are_rejected(client, params):
    assert client.get("/api/employees", params=params).status_code == 422


def test_employee_detail(client, dataset):
    person = employee_with(dataset, lambda e: e["employment_status"] == "terminated" and e["manager_id"])
    body = client.get(f"/api/employees/{person['id']}").json()
    assert body["employee_id"] == person["employee_id"]
    assert body["manager"]["id"] == person["manager_id"]
    assert body["identity_account"]["account_status"] in ("active", "disabled")
    expected_groups = sum(g["employee_id"] == person["id"] for g in dataset["group_memberships"])
    assert len(body["groups"]) == expected_groups


def test_employee_without_account(client, dataset):
    with_accounts = {a["employee_id"] for a in dataset["identity_accounts"]}
    person = employee_with(dataset, lambda e: e["id"] not in with_accounts)
    body = client.get(f"/api/employees/{person['id']}").json()
    assert body["identity_account"] is None
    assert body["groups"] == []


@pytest.mark.parametrize("suffix", ["", "/activity", "/workflows", "/changes"])
def test_unknown_employee_returns_404(client, suffix):
    response = client.get(f"/api/employees/999999{suffix}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Employee 999999 not found"}


def test_non_numeric_employee_id_is_rejected(client):
    assert client.get("/api/employees/EMP00042").status_code == 422


def test_activity_is_newest_first_and_covers_all_sources(client, dataset):
    failed_sync = Counter(r["employee_id"] for r in dataset["sync_record_results"] if r["status"] == "failed")
    person_id = failed_sync.most_common(1)[0][0]
    events = client.get(f"/api/employees/{person_id}/activity").json()
    timestamps = [event["timestamp"] for event in events]
    assert timestamps == sorted(timestamps, reverse=True)
    categories = {event["category"] for event in events}
    assert {"sync", "data_quality"} <= categories


def test_workflows_include_their_actions(client, dataset):
    failed = next(r for r in dataset["workflow_runs"] if r["status"] == "failed")
    runs = client.get(f"/api/employees/{failed['employee_id']}/workflows").json()
    run = next(r for r in runs if r["id"] == failed["id"])
    expected = sum(a["workflow_run_id"] == failed["id"] for a in dataset["workflow_actions"])
    assert len(run["actions"]) == expected
    assert any(action["status"] == "failed" for action in run["actions"])


def test_changes(client, dataset):
    counts = Counter(c["employee_id"] for c in dataset["attribute_change_logs"])
    person_id, count = counts.most_common(1)[0]
    changes = client.get(f"/api/employees/{person_id}/changes").json()
    assert len(changes) == count


# --- analytics ----------------------------------------------------------------------------

ANALYTICS_ENDPOINTS = [
    "sync-summary",
    "sync-trends",
    "attribute-changes",
    "workflow-summary",
    "workflow-failures",
    "data-quality",
    "offboarding",
    "group-cleanup",
    "license-cleanup",
]


@pytest.mark.parametrize("endpoint", ANALYTICS_ENDPOINTS)
def test_analytics_endpoints_respond(client, endpoint):
    response = client.get(f"/api/analytics/{endpoint}")
    assert response.status_code == 200
    assert response.json()["period"] == {"start_date": None, "end_date": None}


@pytest.mark.parametrize("endpoint", ANALYTICS_ENDPOINTS)
def test_reversed_date_range_is_rejected(client, endpoint):
    response = client.get(f"/api/analytics/{endpoint}", params={"start_date": "2026-05-01", "end_date": "2026-04-01"})
    assert response.status_code == 422


def test_invalid_date_is_rejected(client):
    assert client.get("/api/analytics/sync-summary", params={"start_date": "not-a-date"}).status_code == 422


def test_date_range_narrows_results(client, dataset):
    whole_year = client.get("/api/analytics/sync-summary").json()["totals"]
    january = client.get(
        "/api/analytics/sync-summary", params={"start_date": "2026-01-01", "end_date": "2026-01-31"}
    ).json()["totals"]
    expected = sum(r["started_at"].strftime("%Y-%m") == "2026-01" for r in dataset["sync_runs"])
    assert january["total_runs"] == expected
    assert january["total_runs"] < whole_year["total_runs"]


def test_sync_summary_matches_the_data(client, dataset):
    totals = client.get("/api/analytics/sync-summary").json()["totals"]
    assert totals["total_runs"] == len(dataset["sync_runs"])
    assert totals["records_failed"] == sum(r["status"] == "failed" for r in dataset["sync_record_results"])


def test_workflow_failures_threshold(client):
    loose = client.get("/api/analytics/workflow-failures", params={"min_failures": 1}).json()
    strict = client.get("/api/analytics/workflow-failures", params={"min_failures": 5}).json()
    assert len(strict["repeated_failures"]) < len(loose["repeated_failures"])
    assert all(row["total_failures"] >= 5 for row in strict["repeated_failures"])


def test_offboarding_shows_remaining_access(client, dataset):
    body = client.get("/api/analytics/offboarding").json()
    assert body["time_to_disable"]["terminated_with_account"] > 0
    assert body["access_remaining"]
    assert all(row["employee_db_id"] for row in body["access_remaining"])
