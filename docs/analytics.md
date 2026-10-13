# Analytics

All metrics come from named SQL queries in [`app/analytics/sql/`](../app/analytics/sql/).
Each file starts with the question it answers and can be run directly in `psql`.
[`app/analytics/queries.py`](../app/analytics/queries.py) is the registry: the API can only
run queries listed there, and the AI layer chooses from the same list instead of generating
SQL ([ai.md](ai.md)).

Every query is tested against the same figure computed separately in Python from the
generated rows (`tests/test_analytics.py`).

## Conventions

- **Date filters.** Most queries take `:start_date` (inclusive) and `:end_date` (exclusive).
  The API accepts inclusive calendar dates and converts them, so `end_date=2026-01-31`
  includes all of 31 January. Queries marked *current state* ignore the date range.
- **Time zone.** Timestamps are stored in UTC and grouped into months in UTC.
- **Department and location** are the employee's *current* values. A transfer is counted under
  the new department, and invalid values (e.g. `Logistics` after the merge) appear as they are.
- **Percentages** are 0–100 with one decimal place, and NULL when there is nothing to divide by.

## Metric definitions

| Metric | Definition |
|--------|------------|
| Record success rate (sync) | records updated / (records updated + records failed). Skipped records (unchanged, terminated, or held after 3 failures) are excluded because no update was attempted. |
| Run failure rate (sync) | runs with status `failed` / all runs. A failed run is a file-level or directory failure, not a run with some failed records. |
| Workflow success rate | completed / (completed + failed). Pending workflows have not run and are excluded. |
| First-time offboarding success | offboardings started by the nightly sync that completed without a service-desk re-run. |
| Action failure rate | failed / attempted, where attempted excludes `skipped` actions (already disabled, or not attempted after `create_account` failed). |
| Workflow duration | `completed_at - started_at`. Queue time before a pending workflow starts is not included. |
| Time to disable account | account `disabled_at` minus the time HR changed the status to `terminated`. Negative values mean the account was already disabled for a leave of absence. Employees whose status was never changed are not included; they show up as `incorrect_employment_status` issues. |
| Days to resolve (data quality) | `resolved_at - detected_at`, for resolved issues only. |

## Queries

| Endpoint | Query | Question |
|----------|-------|----------|
| `/api/analytics/sync-summary` | `sync_summary` | How reliable was the HR → identity sync? |
| | `sync_failures_by_error_type` | Why do sync records fail? |
| | `sync_failures_by_department` | Which departments' records fail to sync most often? |
| | `sync_failures_by_location` | Do sync failures cluster at particular sites? |
| | `sync_run_durations` | How long do sync runs take, scheduled vs manual? |
| `/api/analytics/sync-trends` | `sync_monthly_trend` | How did sync volume and failures change by month? |
| `/api/analytics/attribute-changes` | `attribute_changes_by_attribute` | Which HR attributes change most often, and how many changes are corrections? |
| | `attribute_changes_by_department` | Which departments generate the most HR changes? |
| | `most_changed_employees` | Which employees had the most HR changes? |
| `/api/analytics/workflow-summary` | `workflow_summary` | How many workflows ran and how many succeeded? |
| | `workflow_durations` | How long does each type of workflow take (avg, median, p90)? |
| | `workflow_monthly_trend` | How does workflow volume and failure change by month? |
| | `pending_workflows` *(current state)* | Which workflows are waiting to run? |
| `/api/analytics/workflow-failures` | `action_failure_rates` | Which workflow actions fail most often? |
| | `action_failures_by_error_type` | What kind of error causes each action failure? |
| | `repeated_operational_failures` | Which employees keep running into failures across sync and workflows? |
| *(AI layer only)* | `workflow_action_failures` | Which actions failed in one type of workflow, and why? |
| `/api/analytics/offboarding` | `offboarding_monthly` | How many offboardings ran each month and how many needed a re-run? |
| | `time_to_disable_account` | How quickly are accounts disabled after termination? |
| | `access_remaining_after_offboarding` *(current state)* | Which leavers still have an enabled account or access? |
| `/api/analytics/group-cleanup` | `group_cleanup_summary` | Which groups fail to be removed, and how many leavers are still members? |
| `/api/analytics/license-cleanup` | `license_cleanup_summary` | Which licenses fail to be removed, and how many are still assigned to leavers? |
| `/api/analytics/data-quality` | `dq_summary` | How many issues were found and how fast are they resolved? |
| | `dq_by_type` | Which problems occur, on which fields, at what severity? |
| | `dq_by_department` | Which departments have the most issues? |
| | `dq_monthly_trend` | Are issues found faster than they are fixed? |
| | `employees_with_open_issues` *(current state)* | Which employees have unresolved issues? |
| | `sync_failures_with_open_dq_issue` | Do records with an open issue fail to sync more often? |

## Interpreting the results honestly

The data is synthetic. Patterns built into the simulation (see
[data-generation.md](data-generation.md)) will show up in these queries. They are useful for
demonstrating the analysis, not evidence about real identity systems.

- **Data quality vs sync failures.** `sync_failures_with_open_dq_issue` shows records with an
  open issue failing far more often. In this dataset that is true by construction, because the
  sync validates the same rules the data-quality scan checks. The query shows an association.
  It doesn't prove cause on its own.
- **License removal vs group removal.** License removal fails more often because the simulation
  assumes a less reliable licensing API. The data shows *that* it happens, not *why*.
- **Small numbers.** Some breakdowns (per license, per site, per month) have only a handful of
  failures. Treat differences between small groups with caution.
- **Removed assumption.** An early version assumed slower links at one site. With realistic volumes
  the effect was not distinguishable from noise, so it was removed rather than tuned up.

## API

Run locally:

```bash
uvicorn app.main:app --reload
```

Interactive documentation is at `http://127.0.0.1:8000/docs`. The endpoints below are read-only;
the endpoints that change data (HR changes, sync runs, re-runs, scans) are described in
[operations.md](operations.md).

| Endpoint | Purpose |
|----------|---------|
| `GET /api/employees?search=&department=&employment_status=&limit=&offset=` | Search and filter employees (search matches HR ID, name, email) |
| `GET /api/employees/{id}` | Employee, manager, identity account, all group/role/license assignments, data-quality issues |
| `GET /api/employees/{id}/activity` | Timeline of audit events, failed sync attempts and data-quality findings, newest first |
| `GET /api/employees/{id}/workflows` | Workflow runs with their actions |
| `GET /api/employees/{id}/changes` | HR attribute change history |
| `GET /api/analytics/...` | The analytics endpoints above. All accept `start_date` and `end_date` (YYYY-MM-DD). |

`{id}` is the database id (`employees.id`), not the HR employee ID, because the HR ID can be
missing or duplicated. Search for an HR ID with `?search=EMP00042`.

Errors: unknown employee → `404`; invalid parameters (bad date, `start_date` after `end_date`,
limit out of range) → `422`.
