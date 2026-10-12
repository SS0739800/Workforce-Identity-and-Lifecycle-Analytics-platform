"""The reporting views that Power BI reads.

Each DAX measure in powerbi/measures.dax is a simple count, sum or ratio over one of these
views. These tests compute the same formulas in SQL and compare them with the analytics
queries the API uses, so the report and the API cannot disagree.
"""

import secrets

import psycopg
import pytest
from sqlalchemy import text

from app.db.reporting_access import grant_reporting_access
from app.services.analytics_service import run_query

VIEWS_AND_SOURCES = {
    "dim_employee": "employees",
    "fact_sync_runs": "sync_runs",
    "fact_sync_records": "sync_record_results",
    "fact_workflow_runs": "workflow_runs",
    "fact_workflow_actions": "workflow_actions",
    "fact_attribute_changes": "attribute_change_logs",
    "fact_dq_issues": "data_quality_issues",
}


def scalar(session, sql: str):
    return session.execute(text(sql)).scalar_one()


@pytest.mark.parametrize("view, source", VIEWS_AND_SOURCES.items())
def test_each_view_has_one_row_per_source_row(session, view, source):
    assert scalar(session, f"SELECT count(*) FROM reporting.{view}") == scalar(session, f"SELECT count(*) FROM {source}")


@pytest.mark.parametrize("view, column", [
    ("fact_sync_runs", "date"),
    ("fact_sync_records", "date"),
    ("fact_workflow_runs", "date"),
    ("fact_workflow_actions", "date"),
    ("fact_attribute_changes", "date"),
    ("fact_dq_issues", "detected_date"),
    ("fact_dq_issues", "resolved_date"),
])
def test_every_fact_date_exists_in_the_date_table(session, view, column):
    missing = scalar(session, f"""
        SELECT count(*) FROM reporting.{view} AS f
        WHERE f.{column} IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM reporting.dim_date AS d WHERE d.date = f.{column})
    """)
    assert missing == 0


@pytest.mark.parametrize("view", ["fact_workflow_runs", "fact_workflow_actions"])
def test_every_workflow_type_is_in_the_workflow_type_dimension(session, view):
    missing = scalar(session, f"""
        SELECT count(*) FROM reporting.{view} AS f
        WHERE NOT EXISTS (SELECT 1 FROM reporting.dim_workflow_type AS t WHERE t.workflow_type = f.workflow_type)
    """)
    assert missing == 0


@pytest.mark.parametrize("view, column", [
    ("fact_sync_runs", "started_at"),
    ("fact_workflow_runs", "requested_at"),
    ("fact_workflow_runs", "started_at"),
    ("fact_workflow_runs", "completed_at"),
])
def test_utc_columns_are_plain_timestamps_with_the_same_instant(session, view, column):
    data_type = scalar(session, f"""
        SELECT data_type FROM information_schema.columns
        WHERE table_schema = 'reporting' AND table_name = '{view}' AND column_name = '{column}_utc'
    """)
    assert data_type == "timestamp without time zone"
    mismatches = scalar(session, f"""
        SELECT count(*) FROM reporting.{view}
        WHERE {column}_utc IS DISTINCT FROM ({column} AT TIME ZONE 'UTC')
    """)
    assert mismatches == 0


def test_date_table_has_one_row_per_day(session):
    assert scalar(session, "SELECT count(*) - count(DISTINCT date) FROM reporting.dim_date") == 0


# --- the measures, computed the way the DAX computes them -----------------------------------

def test_sync_measures_match_the_api(session):
    api = run_query(session, "sync_summary")[0]
    assert scalar(session, "SELECT count(*) FROM reporting.fact_sync_runs") == api["total_runs"]
    assert scalar(session, "SELECT count(*) FROM reporting.fact_sync_runs WHERE status = 'failed'") == api["failed_runs"]
    rate = scalar(session, """
        SELECT round(100.0 * count(*) FILTER (WHERE status = 'success') / count(*), 1)
        FROM reporting.fact_sync_records
    """)
    assert float(rate) == api["record_success_rate_pct"]


def test_workflow_measures_match_the_api(session):
    api = {row["workflow_type"]: row for row in run_query(session, "workflow_summary")}
    rows = session.execute(text("""
        SELECT workflow_type,
               count(*) AS workflows,
               round(100.0 * count(*) FILTER (WHERE status = 'completed')
                     / nullif(count(*) FILTER (WHERE status IN ('completed', 'failed')), 0), 1) AS success_rate
        FROM reporting.fact_workflow_runs
        GROUP BY workflow_type
    """)).all()
    for workflow_type, workflows, success_rate in rows:
        assert workflows == api[workflow_type]["workflows"]
        assert float(success_rate) == api[workflow_type]["success_rate_pct"]


def test_action_failure_rate_matches_the_api(session):
    api = {row["action_type"]: row["failure_rate_pct"] for row in run_query(session, "action_failure_rates")}
    rows = session.execute(text("""
        SELECT action_type,
               round(100.0 * count(*) FILTER (WHERE status = 'failed') / nullif(count(*) FILTER (WHERE is_attempt), 0), 1)
        FROM reporting.fact_workflow_actions
        GROUP BY action_type
    """)).all()
    assert {action: float(rate) if rate is not None else None for action, rate in rows} == api


def test_data_quality_measures_match_the_api(session):
    api = run_query(session, "dq_summary")[0]
    assert scalar(session, "SELECT count(*) FROM reporting.fact_dq_issues WHERE status = 'open'") == api["open_issues"]
    assert scalar(session, "SELECT count(*) FROM reporting.fact_dq_issues WHERE status = 'resolved'") == api["resolved_issues"]
    avg_days = scalar(session, "SELECT round(avg(days_to_resolve), 1) FROM reporting.fact_dq_issues")
    assert float(avg_days) == pytest.approx(api["avg_days_to_resolve"], abs=0.1)
    open_on_employees = scalar(session, "SELECT sum(open_dq_issues) FROM reporting.dim_employee")
    assert open_on_employees == api["open_issues"]


def test_sync_failure_rate_by_open_issue_matches_the_api(session):
    api = {row["had_open_issue"]: row for row in run_query(session, "sync_failures_with_open_dq_issue")}
    rows = session.execute(text("""
        SELECT had_open_dq_issue, count(*),
               round(100.0 * count(*) FILTER (WHERE status = 'failed') / count(*), 1)
        FROM reporting.fact_sync_records
        GROUP BY had_open_dq_issue
    """)).all()
    for flag, attempts, rate in rows:
        assert attempts == api[flag]["sync_attempts"]
        assert float(rate) == api[flag]["failure_rate_pct"]


def test_quarter_labels_sort_by_quarter_start(session):
    pairs = session.execute(text("SELECT DISTINCT quarter_label, quarter_start FROM reporting.dim_date")).all()
    assert len(pairs) == len({label for label, _ in pairs}) == len({start for _, start in pairs})


def test_leavers_with_access_match_the_api(session):
    api = run_query(session, "access_remaining_after_offboarding")
    flagged = scalar(session, "SELECT count(*) FROM reporting.dim_employee WHERE has_access_after_termination")
    assert flagged == len(api)


def test_employee_dimension_leaves_out_email(session):
    columns = session.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'reporting' AND table_name = 'dim_employee'
    """)).scalars().all()
    assert "email" not in columns


# --- the Power BI login -----------------------------------------------------------------------

@pytest.fixture
def reader(loaded_engine):
    username = f"test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    grant_reporting_access(loaded_engine, username, password)
    url = loaded_engine.url.set(drivername="postgresql", username=username, password=password)
    yield url.render_as_string(hide_password=False)
    with loaded_engine.begin() as conn:
        conn.execute(text(f'DROP OWNED BY "{username}"'))
        conn.execute(text(f'DROP ROLE "{username}"'))


def test_reporting_login_can_only_read_reporting_views(reader):
    with psycopg.connect(reader, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM reporting.fact_sync_runs").fetchone()[0] > 0
        for statement in [
            "SELECT count(*) FROM public.employees",
            "DELETE FROM reporting.fact_sync_runs",
            "CREATE TABLE reporting.not_allowed (id int)",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


def test_running_the_grant_again_resets_the_password(loaded_engine, reader):
    details = psycopg.conninfo.conninfo_to_dict(reader)
    grant_reporting_access(loaded_engine, details["user"], "a-new-password-123")
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(reader).close()
    new_login = psycopg.conninfo.make_conninfo(reader, password="a-new-password-123")
    with psycopg.connect(new_login) as conn:
        assert conn.execute("SELECT count(*) FROM reporting.dim_date").fetchone()[0] > 0
