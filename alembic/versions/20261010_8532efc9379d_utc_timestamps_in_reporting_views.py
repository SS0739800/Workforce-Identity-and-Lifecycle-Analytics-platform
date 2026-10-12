"""Add plain UTC timestamp columns to the reporting views.

Power BI's PostgreSQL connector did not convert `timestamp with time zone` reliably
(the converted values came through as null), so the views now also expose each timestamp
as a `timestamp without time zone` in UTC, named *_utc. Power Query reads those and drops
the original columns.

The new columns are appended with CREATE OR REPLACE VIEW, which keeps existing grants,
so the Power BI login does not need to be granted access again.

Revision ID: 8532efc9379d
Revises: d09441721c74
Create Date: 2026-10-10 21:45:44.382746

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8532efc9379d'
down_revision: Union[str, Sequence[str], None] = 'd09441721c74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FACT_SYNC_RUNS = """
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
        error_message{extra}
    FROM public.sync_runs
"""

FACT_WORKFLOW_RUNS = """
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
        coalesce(c.failed_actions, 0)                        AS failed_actions{extra}
    FROM public.workflow_runs AS w
    LEFT JOIN action_counts AS c ON c.workflow_run_id = w.id
"""

SYNC_RUNS_UTC = """,
        started_at AT TIME ZONE 'UTC'                        AS started_at_utc"""

WORKFLOW_RUNS_UTC = """,
        w.requested_at AT TIME ZONE 'UTC'                    AS requested_at_utc,
        w.started_at AT TIME ZONE 'UTC'                      AS started_at_utc,
        w.completed_at AT TIME ZONE 'UTC'                    AS completed_at_utc"""


def upgrade() -> None:
    op.execute("CREATE OR REPLACE VIEW reporting.fact_sync_runs AS " + FACT_SYNC_RUNS.format(extra=SYNC_RUNS_UTC))
    op.execute("CREATE OR REPLACE VIEW reporting.fact_workflow_runs AS " + FACT_WORKFLOW_RUNS.format(extra=WORKFLOW_RUNS_UTC))


def downgrade() -> None:
    # Columns can't be removed with CREATE OR REPLACE, so the views are rebuilt.
    # Re-run scripts/create_reporting_user.py afterwards to restore the Power BI login's access.
    op.execute("DROP VIEW reporting.fact_sync_runs")
    op.execute("DROP VIEW reporting.fact_workflow_runs")
    op.execute("CREATE VIEW reporting.fact_sync_runs AS " + FACT_SYNC_RUNS.format(extra=""))
    op.execute("CREATE VIEW reporting.fact_workflow_runs AS " + FACT_WORKFLOW_RUNS.format(extra=""))
