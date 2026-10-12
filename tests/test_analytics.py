"""Check each SQL query against the same figure computed in plain Python from the generated rows.

The two calculations are written independently, so a mistake in either one shows up as a mismatch.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from statistics import mean

import pytest

from app.analytics.queries import QUERIES, SQL_DIR
from app.services.analytics_service import InvalidDateRange, date_bounds, run_query


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def by_key(rows: list[dict], key: str) -> dict:
    return {row[key]: row for row in rows}


# --- registry ---------------------------------------------------------------------------

def test_every_query_has_a_sql_file_and_every_file_is_registered():
    files = {path.stem for path in SQL_DIR.glob("*.sql")}
    assert files == set(QUERIES)
    assert len(QUERIES) >= 20


def test_every_query_runs(session):
    for name in QUERIES:
        run_query(session, name)


def test_unknown_query_is_refused(session):
    with pytest.raises(KeyError):
        run_query(session, "drop_everything")


def test_date_bounds_include_the_whole_end_day():
    start, end = date_bounds(date(2026, 1, 1), date(2026, 1, 31))
    assert start == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 2, 1, tzinfo=timezone.utc)
    with pytest.raises(InvalidDateRange):
        date_bounds(date(2026, 2, 1), date(2026, 1, 1))


# --- sync -------------------------------------------------------------------------------

def test_sync_summary(session, dataset):
    runs = dataset["sync_runs"]
    updated = sum(r["successful_records"] for r in runs)
    failed = sum(r["failed_records"] for r in runs)
    row = run_query(session, "sync_summary")[0]
    assert row["total_runs"] == len(runs)
    assert row["failed_runs"] == sum(r["status"] == "failed" for r in runs)
    assert row["records_evaluated"] == sum(r["total_records"] for r in runs)
    assert row["records_updated"] == updated
    assert row["records_failed"] == failed
    assert row["record_success_rate_pct"] == pct(updated, updated + failed)


def test_sync_summary_respects_date_range(session, dataset):
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    expected = [r for r in dataset["sync_runs"] if start <= r["started_at"].date() <= end]
    row = run_query(session, "sync_summary", start, end)[0]
    assert row["total_runs"] == len(expected)
    assert 0 < len(expected) < len(dataset["sync_runs"])


def test_sync_monthly_trend_adds_up(session, dataset):
    months = run_query(session, "sync_monthly_trend")
    assert len(months) == 12
    assert sum(m["runs"] for m in months) == len(dataset["sync_runs"])
    assert sum(m["records_failed"] for m in months) == sum(r["failed_records"] for r in dataset["sync_runs"])


def test_sync_failures_by_error_type(session, dataset):
    expected = Counter(r["error_type"] for r in dataset["sync_record_results"] if r["status"] == "failed")
    rows = run_query(session, "sync_failures_by_error_type")
    assert {r["error_type"]: r["failures"] for r in rows} == dict(expected)
    assert sum(r["share_pct"] for r in rows) == pytest.approx(100, abs=0.5)


def test_sync_failures_by_department(session, dataset):
    department = {e["id"]: e["department"] or "(blank)" for e in dataset["employees"]}
    attempts, failures = Counter(), Counter()
    for result in dataset["sync_record_results"]:
        attempts[department[result["employee_id"]]] += 1
        failures[department[result["employee_id"]]] += result["status"] == "failed"
    rows = by_key(run_query(session, "sync_failures_by_department"), "department")
    for name, count in attempts.items():
        assert rows[name]["sync_attempts"] == count
        assert rows[name]["failures"] == failures[name]


def test_sync_failures_by_location(session, dataset):
    location = {e["id"]: e["location"] or "(blank)" for e in dataset["employees"]}
    timeouts = Counter(
        location[r["employee_id"]] for r in dataset["sync_record_results"] if r["error_type"] == "TIMEOUT"
    )
    rows = by_key(run_query(session, "sync_failures_by_location"), "location")
    assert sum(r["sync_attempts"] for r in rows.values()) == len(dataset["sync_record_results"])
    assert {name: r["timeouts"] for name, r in rows.items() if r["timeouts"]} == dict(timeouts)


# --- attribute changes ---------------------------------------------------------------------

def test_attribute_changes_by_attribute(session, dataset):
    changes = dataset["attribute_change_logs"]
    expected = Counter(c["attribute_name"] for c in changes)
    corrections = Counter(c["attribute_name"] for c in changes if c["source"] == "data_correction")
    rows = by_key(run_query(session, "attribute_changes_by_attribute"), "attribute_name")
    assert {name: r["changes"] for name, r in rows.items()} == dict(expected)
    assert {name: r["corrections"] for name, r in rows.items() if r["corrections"]} == dict(corrections)


def test_most_changed_employees(session, dataset):
    counts = Counter(c["employee_id"] for c in dataset["attribute_change_logs"])
    rows = run_query(session, "most_changed_employees", limit=5)
    assert len(rows) == 5
    assert rows[0]["changes"] == max(counts.values())
    for row in rows:
        assert row["changes"] == counts[row["id"]]


# --- workflows --------------------------------------------------------------------------------

def test_workflow_summary(session, dataset):
    rows = by_key(run_query(session, "workflow_summary"), "workflow_type")
    by_type = defaultdict(Counter)
    for run in dataset["workflow_runs"]:
        by_type[run["workflow_type"]][run["status"]] += 1
    for workflow_type, statuses in by_type.items():
        row = rows[workflow_type]
        assert row["workflows"] == sum(statuses.values())
        assert row["completed"] == statuses["completed"]
        assert row["failed"] == statuses["failed"]
        assert row["pending"] == statuses["pending"]
        assert row["success_rate_pct"] == pct(statuses["completed"], statuses["completed"] + statuses["failed"])


def test_workflow_durations(session, dataset):
    rows = by_key(run_query(session, "workflow_durations"), "workflow_type")
    seconds = defaultdict(list)
    for run in dataset["workflow_runs"]:
        if run["completed_at"]:
            seconds[run["workflow_type"]].append((run["completed_at"] - run["started_at"]).total_seconds())
    for workflow_type, values in seconds.items():
        assert rows[workflow_type]["workflows"] == len(values)
        assert rows[workflow_type]["avg_seconds"] == pytest.approx(mean(values), abs=0.05)


def test_action_failure_rates(session, dataset):
    rows = by_key(run_query(session, "action_failure_rates"), "action_type")
    attempts, failures = Counter(), Counter()
    for action in dataset["workflow_actions"]:
        if action["status"] != "skipped":
            attempts[action["action_type"]] += 1
        failures[action["action_type"]] += action["status"] == "failed"
    for action_type, count in attempts.items():
        assert rows[action_type]["attempts"] == count
        assert rows[action_type]["failures"] == failures[action_type]
        assert rows[action_type]["failure_rate_pct"] == pct(failures[action_type], count)


def test_action_failures_by_error_type(session, dataset):
    expected = Counter(
        (a["action_type"], a["error_type"]) for a in dataset["workflow_actions"] if a["status"] == "failed"
    )
    rows = run_query(session, "action_failures_by_error_type")
    assert {(r["action_type"], r["error_type"]): r["failures"] for r in rows} == dict(expected)


def test_pending_workflows(session, dataset):
    expected = {r["id"] for r in dataset["workflow_runs"] if r["status"] == "pending"}
    rows = run_query(session, "pending_workflows")
    assert {r["workflow_run_id"] for r in rows} == expected


def test_repeated_operational_failures(session, dataset):
    failures = Counter(r["employee_id"] for r in dataset["sync_record_results"] if r["status"] == "failed")
    run_owner = {run["id"]: run["employee_id"] for run in dataset["workflow_runs"]}
    for action in dataset["workflow_actions"]:
        if action["status"] == "failed":
            failures[run_owner[action["workflow_run_id"]]] += 1
    expected = {employee for employee, count in failures.items() if count >= 3}
    rows = run_query(session, "repeated_operational_failures", min_failures=3, limit=1000)
    assert {r["employee_db_id"] for r in rows} == expected
    for row in rows:
        assert row["total_failures"] == failures[row["employee_db_id"]]


# --- offboarding and cleanup -------------------------------------------------------------------

def test_offboarding_monthly_adds_up(session, dataset):
    started = [r for r in dataset["workflow_runs"] if r["workflow_type"] == "offboarding" and r["started_at"]]
    rows = run_query(session, "offboarding_monthly")
    assert sum(r["offboardings"] for r in rows) == sum(r["initiated_by"] != "service_desk" for r in started)
    assert sum(r["service_desk_reruns"] for r in rows) == sum(r["initiated_by"] == "service_desk" for r in started)


def test_time_to_disable_account(session, dataset):
    terminated_at = {}
    for change in dataset["attribute_change_logs"]:
        if change["attribute_name"] == "employment_status" and change["new_value"] == "terminated":
            terminated_at[change["employee_id"]] = max(change["changed_at"], terminated_at.get(change["employee_id"], change["changed_at"]))
    buckets = Counter()
    for account in dataset["identity_accounts"]:
        employee = account["employee_id"]
        if employee not in terminated_at:
            continue
        buckets["total"] += 1
        if account["account_status"] == "active":
            buckets["still_enabled"] += 1
            continue
        hours = (account["account_disabled_at"] - terminated_at[employee]).total_seconds() / 3600
        if hours < 0:
            buckets["before"] += 1
        elif hours <= 4:
            buckets["4h"] += 1
        elif hours <= 24:
            buckets["24h"] += 1
        else:
            buckets["later"] += 1

    row = run_query(session, "time_to_disable_account")[0]
    assert row["terminated_with_account"] == buckets["total"]
    assert row["still_enabled"] == buckets["still_enabled"]
    assert row["disabled_before_termination"] == buckets["before"]
    assert row["disabled_within_4_hours"] == buckets["4h"]
    assert row["disabled_within_24_hours"] == buckets["24h"]
    assert row["disabled_after_24_hours"] == buckets["later"]


def terminated_ids(dataset) -> set[int]:
    return {e["id"] for e in dataset["employees"] if e["employment_status"] == "terminated"}


@pytest.mark.parametrize("query, table, name_column, action_type", [
    ("group_cleanup_summary", "group_memberships", "group_name", "remove_group_membership"),
    ("license_cleanup_summary", "license_assignments", "license_name", "remove_license"),
])
def test_cleanup_summaries(session, dataset, query, table, name_column, action_type):
    leavers = terminated_ids(dataset)
    remaining = Counter(
        row[name_column] for row in dataset[table] if row["status"] == "active" and row["employee_id"] in leavers
    )
    attempts = Counter(
        a["target_name"] for a in dataset["workflow_actions"] if a["action_type"] == action_type and a["status"] != "skipped"
    )
    rows = by_key(run_query(session, query), name_column)
    assert {name: r["still_assigned_to_terminated"] for name, r in rows.items() if r["still_assigned_to_terminated"]} == dict(remaining)
    assert {name: r["removal_attempts"] for name, r in rows.items() if r["removal_attempts"]} == dict(attempts)


def test_access_remaining_after_offboarding(session, dataset):
    leavers = terminated_ids(dataset)
    expected = {a["employee_id"] for a in dataset["identity_accounts"] if a["account_status"] == "active"} & leavers
    for table in ("group_memberships", "role_assignments", "license_assignments"):
        expected |= {r["employee_id"] for r in dataset[table] if r["status"] == "active" and r["employee_id"] in leavers}
    rows = run_query(session, "access_remaining_after_offboarding")
    assert {r["employee_db_id"] for r in rows} == expected


# --- data quality -------------------------------------------------------------------------------

def test_dq_summary(session, dataset):
    issues = dataset["data_quality_issues"]
    resolved = [i for i in issues if i["status"] == "resolved"]
    row = run_query(session, "dq_summary")[0]
    assert row["total_issues"] == len(issues)
    assert row["open_issues"] == len(issues) - len(resolved)
    assert row["resolved_issues"] == len(resolved)
    assert row["employees_with_open_issues"] == len({i["employee_id"] for i in issues if i["status"] == "open"})
    expected_days = mean((i["resolved_at"] - i["detected_at"]).total_seconds() / 86400 for i in resolved)
    assert row["avg_days_to_resolve"] == pytest.approx(expected_days, abs=0.05)


def test_dq_by_type(session, dataset):
    expected = Counter(i["issue_type"] for i in dataset["data_quality_issues"])
    rows = run_query(session, "dq_by_type")
    totals = Counter()
    for row in rows:
        totals[row["issue_type"]] += row["issues"]
    assert totals == expected


def test_dq_monthly_trend_adds_up(session, dataset):
    issues = dataset["data_quality_issues"]
    rows = run_query(session, "dq_monthly_trend")
    assert sum(r["detected"] for r in rows) == len(issues)
    assert sum(r["resolved"] for r in rows) == sum(i["resolved_at"] is not None for i in issues)


def test_employees_with_open_issues(session, dataset):
    expected = Counter(i["employee_id"] for i in dataset["data_quality_issues"] if i["status"] == "open")
    rows = run_query(session, "employees_with_open_issues")
    assert {r["employee_db_id"]: r["open_issues"] for r in rows} == dict(expected)
    assert rows[0]["highest_severity"] == "critical"


def test_sync_failures_with_open_dq_issue(session, dataset):
    issues = defaultdict(list)
    for issue in dataset["data_quality_issues"]:
        issues[issue["employee_id"]].append(issue)

    def had_open_issue(result) -> bool:
        return any(
            i["detected_at"] <= result["started_at"] and (i["resolved_at"] is None or i["resolved_at"] > result["started_at"])
            for i in issues[result["employee_id"]]
        )

    attempts, failures = Counter(), Counter()
    for result in dataset["sync_record_results"]:
        flag = had_open_issue(result)
        attempts[flag] += 1
        failures[flag] += result["status"] == "failed"

    rows = by_key(run_query(session, "sync_failures_with_open_dq_issue"), "had_open_issue")
    for flag in (True, False):
        assert rows[flag]["sync_attempts"] == attempts[flag]
        assert rows[flag]["failures"] == failures[flag]
    # The association the data is designed to show: flagged records fail far more often.
    assert rows[True]["failure_rate_pct"] > rows[False]["failure_rate_pct"] * 5


@pytest.mark.parametrize("workflow_type", ["onboarding", "offboarding", "leave"])
def test_workflow_action_failures(session, dataset, workflow_type):
    run_type = {run["id"]: run["workflow_type"] for run in dataset["workflow_runs"]}
    expected = Counter(
        (a["action_type"], a["error_type"]) for a in dataset["workflow_actions"]
        if a["status"] == "failed" and run_type[a["workflow_run_id"]] == workflow_type
    )
    rows = run_query(session, "workflow_action_failures", workflow_type=workflow_type)
    assert {(r["action_type"], r["error_type"]): r["failures"] for r in rows} == dict(expected)
