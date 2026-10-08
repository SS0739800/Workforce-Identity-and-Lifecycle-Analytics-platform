from collections import Counter, defaultdict
from datetime import timedelta

from app.etl.loader import validate
from app.lifecycle.reference import ERROR_TYPES
from app.lifecycle.sync import MAX_SYNC_ATTEMPTS
from app.lifecycle.validation import check_hr_record, check_identity_state, find_duplicates
from app.synthetic import assumptions as A
from app.synthetic.simulator import at, generate


def by_id(rows: list[dict]) -> dict[int, dict]:
    return {row["id"]: row for row in rows}


# --- size and reproducibility -------------------------------------------------------

def test_workforce_is_about_one_thousand_people(dataset):
    employees = dataset["employees"]
    assert 950 <= len(employees) <= 1100
    statuses = Counter(e["employment_status"] for e in employees)
    assert statuses["terminated"] > 80
    assert statuses["active"] > 800


def test_same_seed_gives_identical_data(dataset):
    assert generate(A.DEFAULT_SEED) == dataset


def test_different_seed_gives_different_data(dataset):
    other = generate(7)
    assert other["employees"] != dataset["employees"]


def test_all_relationships_resolve(dataset):
    # Same checks the loader runs before writing to PostgreSQL: ids, required columns, foreign keys.
    assert validate(dataset) == []


def test_one_account_per_employee_with_unique_usernames(dataset):
    accounts = dataset["identity_accounts"]
    assert len({a["employee_id"] for a in accounts}) == len(accounts)
    assert len({a["username"] for a in accounts}) == len(accounts)


def test_no_real_email_domains(dataset):
    domains = {e["email"].split("@")[-1] for e in dataset["employees"] if e["email"] and "@" in e["email"]}
    assert all(domain.endswith(".example") or "." not in domain for domain in domains)


# --- data quality --------------------------------------------------------------------

def test_most_records_are_clean(dataset):
    employees_with_open_issue = {i["employee_id"] for i in dataset["data_quality_issues"] if i["status"] == "open"}
    assert len(employees_with_open_issue) / len(dataset["employees"]) < 0.05


def test_expected_issue_types_occur(dataset):
    types = {i["issue_type"] for i in dataset["data_quality_issues"]}
    expected = {
        "missing_manager", "invalid_email", "invalid_location", "invalid_department",
        "missing_identity_account", "stale_group_membership", "license_on_inactive_employee",
        "missing_termination_date", "incorrect_employment_status",
    }
    assert expected <= types


def test_open_issues_match_the_rules_on_final_data(dataset):
    """The last scan ran after the last change, so open issues must equal what the rules find now."""
    employees = dataset["employees"]
    accounts = {a["employee_id"]: a for a in dataset["identity_accounts"]}
    active_counts = defaultdict(Counter)
    for table in ("group_memberships", "role_assignments", "license_assignments"):
        for row in dataset[table]:
            if row["status"] == "active":
                active_counts[row["employee_id"]][table] += 1

    last_scan = at(A.SIMULATION_END, 18)
    duplicates = find_duplicates(employees)
    expected = set()
    for employee in employees:
        account = accounts.get(employee["id"])
        counts = active_counts[employee["id"]]
        findings = check_hr_record(employee, last_scan.date(), duplicates.get(employee["id"]))
        findings += check_identity_state(
            employee, last_scan, account["account_status"] if account else None,
            counts["group_memberships"], counts["role_assignments"], counts["license_assignments"],
            is_duplicate=employee["id"] in duplicates,
        )
        expected |= {(employee["id"], f.issue_type) for f in findings}

    open_issues = {(i["employee_id"], i["issue_type"]) for i in dataset["data_quality_issues"] if i["status"] == "open"}
    assert open_issues == expected


def test_resolved_issues_have_resolution_time(dataset):
    for issue in dataset["data_quality_issues"]:
        if issue["status"] == "resolved":
            assert issue["resolved_at"] > issue["detected_at"]
        else:
            assert issue["resolved_at"] is None


def test_data_validation_failures_follow_a_detected_issue(dataset):
    """A record that fails sync validation already has a data-quality issue logged against it."""
    detected = defaultdict(list)
    for issue in dataset["data_quality_issues"]:
        detected[issue["employee_id"]].append(issue["detected_at"])
    validation_errors = {"MISSING_ATTRIBUTE", "INVALID_ATTRIBUTE", "VALIDATION_ERROR"}
    failures = [r for r in dataset["sync_record_results"] if r["error_type"] in validation_errors]
    assert failures
    for result in failures:
        assert any(t <= result["started_at"] for t in detected[result["employee_id"]])


# --- sync -------------------------------------------------------------------------------

def test_sync_run_totals_add_up(dataset):
    results_by_run = defaultdict(Counter)
    for result in dataset["sync_record_results"]:
        results_by_run[result["sync_run_id"]][result["status"]] += 1
    for run in dataset["sync_runs"]:
        counts = results_by_run[run["id"]]
        assert run["successful_records"] == counts["success"]
        assert run["failed_records"] == counts["failed"]
        assert run["total_records"] == run["successful_records"] + run["failed_records"] + run["skipped_records"]


def test_one_scheduled_sync_per_day_plus_manual_reruns(dataset):
    runs = Counter(r["triggered_by"] for r in dataset["sync_runs"])
    days = (A.SIMULATION_END - A.SIMULATION_START).days + 1
    assert runs["schedule"] == days
    assert runs["manual"] == len(A.DIRECTORY_OUTAGE_DATES)


def test_file_level_failures_are_recorded_on_the_run(dataset):
    failed = [r for r in dataset["sync_runs"] if r["status"] == "failed"]
    assert len(failed) == len(A.DIRECTORY_OUTAGE_DATES) + len(A.MISSING_EXPORT_DATES) + len(A.MISSING_COLUMN_DATES)
    assert all(r["error_message"] for r in failed)


def test_failed_records_are_retried_at_most_three_times_per_change(dataset):
    """A record stops being retried after the limit until its HR data changes.

    Directory-outage failures are excluded because they do not count against the limit.
    """
    changes = defaultdict(list)
    for change in dataset["attribute_change_logs"]:
        changes[change["employee_id"]].append(change["changed_at"])

    streak = Counter()
    previous = {}
    longest = 0
    for result in sorted(dataset["sync_record_results"], key=lambda r: r["started_at"]):
        if result["error_type"] == "DEPENDENCY_ERROR":
            continue
        employee_id = result["employee_id"]
        last_seen = previous.get(employee_id)
        if last_seen and any(last_seen < t <= result["started_at"] for t in changes[employee_id]):
            streak[employee_id] = 0
        streak[employee_id] = streak[employee_id] + 1 if result["status"] == "failed" else 0
        longest = max(longest, streak[employee_id])
        previous[employee_id] = result["started_at"]

    assert longest == MAX_SYNC_ATTEMPTS


# --- workflows -------------------------------------------------------------------------

def test_workflow_status_matches_its_actions(dataset):
    actions = defaultdict(list)
    for action in dataset["workflow_actions"]:
        actions[action["workflow_run_id"]].append(action)
    for run in dataset["workflow_runs"]:
        statuses = {a["status"] for a in actions[run["id"]]}
        if run["status"] == "failed":
            assert "failed" in statuses
        elif run["status"] == "completed":
            assert "failed" not in statuses
            assert run["started_at"] <= run["completed_at"]
        elif run["status"] == "pending":
            assert not actions[run["id"]]
            assert run["started_at"] is None


def test_pending_offboarding_only_for_future_terminations(dataset):
    employees = by_id(dataset["employees"])
    pending = [r for r in dataset["workflow_runs"] if r["status"] == "pending"]
    assert pending
    for run in pending:
        employee = employees[run["employee_id"]]
        assert run["workflow_type"] == "offboarding"
        assert employee["employment_status"] == "active"
        assert employee["termination_date"] is not None


def test_completed_offboarding_leaves_no_access(dataset):
    latest = {}
    for run in dataset["workflow_runs"]:
        if run["workflow_type"] == "offboarding" and run["status"] != "pending":
            latest[run["employee_id"]] = run
    accounts = {a["employee_id"]: a for a in dataset["identity_accounts"]}
    remaining = Counter()
    for table in ("group_memberships", "role_assignments", "license_assignments"):
        for row in dataset[table]:
            if row["status"] == "active":
                remaining[row["employee_id"]] += 1

    completed = [run for run in latest.values() if run["status"] == "completed"]
    assert completed
    for run in completed:
        assert remaining[run["employee_id"]] == 0
        assert accounts[run["employee_id"]]["account_status"] == "disabled"


def test_failed_create_account_skips_the_rest_of_onboarding(dataset):
    actions = defaultdict(list)
    for action in dataset["workflow_actions"]:
        actions[action["workflow_run_id"]].append(action)
    for run_actions in actions.values():
        first = run_actions[0]
        if first["action_type"] == "create_account" and first["status"] == "failed":
            assert all(a["status"] == "skipped" for a in run_actions[1:])


def test_only_known_error_types_are_used(dataset):
    used = {a["error_type"] for a in dataset["workflow_actions"]} | {r["error_type"] for r in dataset["sync_record_results"]}
    assert used - {None} <= set(ERROR_TYPES)


def test_timestamps_are_ordered_and_inside_the_year(dataset):
    start = at(A.SIMULATION_START, 0)
    end = at(A.SIMULATION_END, 0) + timedelta(days=1)
    for action in dataset["workflow_actions"]:
        assert start <= action["started_at"] <= action["completed_at"] <= end
    for result in dataset["sync_record_results"]:
        assert start <= result["started_at"] <= result["completed_at"] <= end


# --- documented patterns ----------------------------------------------------------------------

def failure_rate(actions: list[dict]) -> float:
    attempted = [a for a in actions if a["status"] != "skipped"]
    return sum(a["status"] == "failed" for a in attempted) / len(attempted)


def test_license_removal_fails_more_than_group_removal(dataset):
    actions = dataset["workflow_actions"]
    licenses = failure_rate([a for a in actions if a["action_type"] == "remove_license"])
    groups = failure_rate([a for a in actions if a["action_type"] == "remove_group_membership"])
    assert licenses > groups


def test_license_assignment_fails_more_during_shortages(dataset):
    def in_shortage(action):
        day = action["started_at"].date()
        return any(start <= day <= end for start, end in A.LICENSE_SHORTAGE_PERIODS)

    assignments = [a for a in dataset["workflow_actions"] if a["action_type"] == "assign_license"]
    during = failure_rate([a for a in assignments if in_shortage(a)])
    outside = failure_rate([a for a in assignments if not in_shortage(a)])
    assert during > outside * 2


def test_hiring_peaks_in_january_and_june(dataset):
    hires = Counter(
        e["created_at"].month for e in dataset["employees"] if e["created_at"].date() >= A.SIMULATION_START
    )
    assert hires[1] > hires[12]
    assert hires[5] > hires[12]  # interns are entered in May for a June start
