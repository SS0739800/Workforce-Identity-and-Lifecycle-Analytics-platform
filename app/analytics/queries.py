"""Registry of the approved analytical queries.

Each query lives in its own file under sql/ so it can be read, run in psql, or reused in
Power BI as-is. Only queries listed here can be executed by the application (the AI layer
added later will use this same list as its allowlist instead of generating SQL).

Date-filtered queries take :start_date (inclusive) and :end_date (exclusive) timestamps.
"""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

SQL_DIR = Path(__file__).parent / "sql"


@dataclass(frozen=True)
class AnalyticsQuery:
    name: str
    question: str
    uses_date_range: bool = True
    # Extra parameters and their default values.
    defaults: tuple[tuple[str, int | str], ...] = ()

    @cached_property
    def sql(self) -> str:
        return (SQL_DIR / f"{self.name}.sql").read_text(encoding="utf-8")


QUERIES: dict[str, AnalyticsQuery] = {
    q.name: q
    for q in [
        # Synchronization
        AnalyticsQuery("sync_summary", "How reliable was the HR to identity sync?"),
        AnalyticsQuery("sync_monthly_trend", "How did sync volume and failures change by month?"),
        AnalyticsQuery("sync_failures_by_error_type", "Why do sync records fail?"),
        AnalyticsQuery("sync_failures_by_department", "Which departments' records fail to sync most often?"),
        AnalyticsQuery("sync_failures_by_location", "Do sync failures cluster at particular sites?"),
        AnalyticsQuery("sync_run_durations", "How long do sync runs take?"),
        # Attribute changes
        AnalyticsQuery("attribute_changes_by_attribute", "Which HR attributes change most often?"),
        AnalyticsQuery("attribute_changes_by_department", "Which departments generate the most HR changes?"),
        AnalyticsQuery("most_changed_employees", "Which employees had the most HR changes?",
                       defaults=(("limit", 20),)),
        # Workflows
        AnalyticsQuery("workflow_summary", "How many lifecycle workflows ran and how many succeeded?"),
        AnalyticsQuery("workflow_monthly_trend", "How does workflow volume and failure change by month?"),
        AnalyticsQuery("workflow_durations", "How long does each type of workflow take?"),
        AnalyticsQuery("action_failure_rates", "Which workflow actions fail most often?"),
        AnalyticsQuery("action_failures_by_error_type", "What kind of error causes each action failure?"),
        AnalyticsQuery("workflow_action_failures", "Which actions failed in one type of workflow, and why?",
                       defaults=(("workflow_type", "offboarding"),)),
        AnalyticsQuery("pending_workflows", "Which workflows are waiting to run?", uses_date_range=False),
        AnalyticsQuery("repeated_operational_failures", "Which employees keep running into failures?",
                       defaults=(("min_failures", 3), ("limit", 25))),
        # Offboarding and access cleanup
        AnalyticsQuery("offboarding_monthly", "How many offboardings ran each month and how many failed?"),
        AnalyticsQuery("time_to_disable_account", "How quickly are accounts disabled after termination?"),
        AnalyticsQuery("group_cleanup_summary", "Which groups fail to be removed at offboarding?"),
        AnalyticsQuery("license_cleanup_summary", "Which licenses fail to be removed at offboarding?"),
        AnalyticsQuery("access_remaining_after_offboarding",
                       "Which terminated employees still have an enabled account or access?",
                       uses_date_range=False),
        # Data quality
        AnalyticsQuery("dq_summary", "How many data-quality issues were found and how fast are they resolved?"),
        AnalyticsQuery("dq_by_type", "Which data-quality problems occur and on which fields?"),
        AnalyticsQuery("dq_by_department", "Which departments have the most data-quality issues?"),
        AnalyticsQuery("dq_monthly_trend", "Are issues found faster than they are fixed?"),
        AnalyticsQuery("employees_with_open_issues", "Which employees have unresolved data-quality issues?",
                       uses_date_range=False),
        AnalyticsQuery("sync_failures_with_open_dq_issue",
                       "Do records with an open data-quality issue fail to sync more often?"),
    ]
}
