"""Add the reporting schema: views shaped for Power BI.

One date dimension, one employee dimension, and one fact view per kind of event.
Dates are UTC calendar dates. Keys are the source table ids, so every row in Power BI
can be traced back to its source row.

Revision ID: d09441721c74
Revises: 5e8cfee4a5ea
Create Date: 2026-10-08 14:43:34.814284

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd09441721c74'
down_revision: Union[str, Sequence[str], None] = '5e8cfee4a5ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VIEWS = {
    # Whole calendar years covering every sync run, so the date slicer never has gaps.
    "dim_date": """
        WITH bounds AS (
            SELECT
                date_trunc('year', min(started_at AT TIME ZONE 'UTC'))::date AS first_day,
                (date_trunc('year', max(started_at AT TIME ZONE 'UTC')) + interval '1 year - 1 day')::date AS last_day
            FROM public.sync_runs
        )
        SELECT
            day::date                               AS date,
            extract(year FROM day)::int             AS year,
            extract(quarter FROM day)::int          AS quarter,
            'Q' || extract(quarter FROM day) || ' ' || extract(year FROM day) AS quarter_label,
            date_trunc('quarter', day)::date        AS quarter_start,
            extract(month FROM day)::int            AS month_number,
            date_trunc('month', day)::date          AS month_start,
            to_char(day, 'Mon YYYY')                AS month_label,
            extract(isodow FROM day)::int           AS day_of_week,
            extract(isodow FROM day) < 6            AS is_weekday
        FROM bounds, generate_series(bounds.first_day, bounds.last_day, interval '1 day') AS day
    """,
    # Current HR state per employee. Email is left out: reports don't need it.
    "dim_employee": """
        WITH active_access AS (
            SELECT employee_id FROM public.group_memberships WHERE status = 'active'
            UNION
            SELECT employee_id FROM public.role_assignments WHERE status = 'active'
            UNION
            SELECT employee_id FROM public.license_assignments WHERE status = 'active'
        ),
        open_issues AS (
            SELECT employee_id, count(*) AS open_issues
            FROM public.data_quality_issues
            WHERE status = 'open'
            GROUP BY employee_id
        )
        SELECT
            e.id                                         AS employee_key,
            e.employee_id                                AS hr_employee_id,
            e.first_name || ' ' || e.last_name           AS employee_name,
            coalesce(e.department, '(blank)')            AS department,
            coalesce(e.job_title, '(blank)')             AS job_title,
            coalesce(e.location, '(blank)')              AS location,
            e.employment_type,
            e.employment_status,
            e.leave_status,
            e.hire_date,
            e.termination_date,
            m.first_name || ' ' || m.last_name           AS manager_name,
            coalesce(a.account_status, 'no account')     AS account_status,
            e.employment_status = 'terminated'
                AND (a.account_status = 'active' OR x.employee_id IS NOT NULL)
                                                         AS has_access_after_termination,
            coalesce(o.open_issues, 0)                   AS open_dq_issues
        FROM public.employees AS e
        LEFT JOIN public.employees AS m ON m.id = e.manager_id
        LEFT JOIN public.identity_accounts AS a ON a.employee_id = e.id
        LEFT JOIN active_access AS x ON x.employee_id = e.id
        LEFT JOIN open_issues AS o ON o.employee_id = e.id
    """,
    # Shared by fact_workflow_runs and fact_workflow_actions, so one slicer filters both.
    "dim_workflow_type": """
        SELECT workflow_type, workflow_label, sort_order
        FROM (VALUES
            ('onboarding', 'Onboarding', 1),
            ('offboarding', 'Offboarding', 2),
            ('leave', 'Leave', 3),
            ('return_from_leave', 'Return from leave', 4)
        ) AS types (workflow_type, workflow_label, sort_order)
    """,
    "fact_sync_runs": """
        SELECT
            id                                                   AS sync_run_key,
            run_id,
            (started_at AT TIME ZONE 'UTC')::date                AS date,
            started_at,
            status,
            triggered_by,
            total_records,
            successful_records,
            failed_records,
            skipped_records,
            extract(epoch FROM completed_at - started_at)::numeric(10, 1) AS duration_seconds,
            error_message
        FROM public.sync_runs
    """,
    # had_open_dq_issue: whether the employee had an unresolved data-quality issue at the time
    # of the attempt. Same definition as the sync_failures_with_open_dq_issue analytics query.
    "fact_sync_records": """
        SELECT
            r.id                                                 AS sync_record_key,
            r.sync_run_id                                        AS sync_run_key,
            r.employee_id                                        AS employee_key,
            (r.started_at AT TIME ZONE 'UTC')::date              AS date,
            r.status,
            r.error_type,
            extract(epoch FROM r.completed_at - r.started_at)::numeric(10, 1) AS duration_seconds,
            EXISTS (
                SELECT 1
                FROM public.data_quality_issues AS d
                WHERE d.employee_id = r.employee_id
                  AND d.detected_at <= r.started_at
                  AND (d.resolved_at IS NULL OR d.resolved_at > r.started_at)
            )                                                    AS had_open_dq_issue
        FROM public.sync_record_results AS r
    """,
    "fact_workflow_runs": """
        WITH action_counts AS (
            SELECT
                workflow_run_id,
                count(*)                                     AS actions,
                count(*) FILTER (WHERE status = 'failed')    AS failed_actions
            FROM public.workflow_actions
            GROUP BY workflow_run_id
        )
        SELECT
            w.id                                                 AS workflow_key,
            w.employee_id                                        AS employee_key,
            (w.requested_at AT TIME ZONE 'UTC')::date            AS date,
            w.workflow_type,
            w.status,
            w.initiated_by,
            w.initiated_by = 'service_desk'                      AS is_rerun,
            w.requested_at,
            w.started_at,
            w.completed_at,
            extract(epoch FROM w.completed_at - w.started_at)::numeric(10, 1) AS duration_seconds,
            coalesce(c.actions, 0)                               AS actions,
            coalesce(c.failed_actions, 0)                        AS failed_actions
        FROM public.workflow_runs AS w
        LEFT JOIN action_counts AS c ON c.workflow_run_id = w.id
    """,
    # Workflow type and employee are copied onto each action so the model needs no fact-to-fact join.
    "fact_workflow_actions": """
        SELECT
            a.id                                                 AS action_key,
            a.workflow_run_id                                    AS workflow_key,
            w.employee_id                                        AS employee_key,
            (a.started_at AT TIME ZONE 'UTC')::date              AS date,
            w.workflow_type,
            a.action_type,
            a.target_name,
            a.status,
            a.status <> 'skipped'                                AS is_attempt,
            a.error_type,
            extract(epoch FROM a.completed_at - a.started_at)::numeric(10, 1) AS duration_seconds
        FROM public.workflow_actions AS a
        JOIN public.workflow_runs AS w ON w.id = a.workflow_run_id
    """,
    "fact_attribute_changes": """
        SELECT
            id                                                   AS change_key,
            employee_id                                          AS employee_key,
            (changed_at AT TIME ZONE 'UTC')::date                AS date,
            attribute_name,
            source,
            source = 'data_correction'                           AS is_correction
        FROM public.attribute_change_logs
    """,
    # Two dates: detected (the active relationship in Power BI) and resolved (an inactive one).
    "fact_dq_issues": """
        SELECT
            id                                                   AS issue_key,
            employee_id                                          AS employee_key,
            (detected_at AT TIME ZONE 'UTC')::date               AS detected_date,
            (resolved_at AT TIME ZONE 'UTC')::date               AS resolved_date,
            issue_type,
            field_name,
            severity,
            status,
            round((extract(epoch FROM resolved_at - detected_at) / 86400)::numeric, 1) AS days_to_resolve
        FROM public.data_quality_issues
    """,
}


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reporting")
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW reporting.{name} AS {sql}")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS reporting CASCADE")
