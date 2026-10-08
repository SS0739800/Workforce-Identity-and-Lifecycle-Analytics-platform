# Data model

PostgreSQL schema created by the Alembic migration in `alembic/versions/`.
Models live in `app/models/`.

```
employees ──┬── identity_accounts        (0..1 per employee)
  (self:    ├── group_memberships
  manager)  ├── role_assignments
            ├── license_assignments
            ├── attribute_change_logs
            ├── workflow_runs ──── workflow_actions
            ├── sync_record_results ──── sync_runs
            ├── data_quality_issues
            └── audit_events

ai_insight_runs   (standalone; used from the AI phase onwards)
```

## Reporting schema

Power BI reads the `reporting` schema, not these tables: views shaped as dimensions
(`dim_date`, `dim_employee`, `dim_workflow_type`) and facts (`fact_sync_runs`,
`fact_sync_records`, `fact_workflow_runs`, `fact_workflow_actions`, `fact_attribute_changes`,
`fact_dq_issues`). They are created by the second Alembic migration and described in
[powerbi/README.md](../powerbi/README.md). A separate read-only login can read only these views.

## Two kinds of "employee ID"

- `employees.employee_id` is the **HR business identifier** (`EMP00042`). It can be missing
  or duplicated, because those are data-quality problems the platform has to detect.
- In every other table, `employee_id` is a **foreign key to `employees.id`** (the surrogate key).

The column names follow the project specification. This distinction is the first thing to
know when writing queries.

## Tables

| Table | One row per | Notes |
|-------|-------------|-------|
| employees | HR record | Current state at the end of the simulated year. History is in `attribute_change_logs`. |
| identity_accounts | Simulated directory account | A PostgreSQL row, **not** an AWS IAM user. Status `active` / `disabled`. |
| group_memberships, role_assignments, license_assignments | Assignment | Removed assignments are kept with `status = 'removed'` and `removed_at`, so history is preserved. |
| attribute_change_logs | Changed HR attribute | `source` is `hr_system` or `data_correction`. |
| sync_runs | Run of the HR → identity sync | `total = successful + failed + skipped`. |
| sync_record_results | Record the sync tried to update | Unchanged records are counted on the run but get no row here. |
| workflow_runs | Lifecycle workflow execution | `onboarding`, `offboarding`, `leave`, `return_from_leave`. `initiated_by` is `nightly_sync`, `manual_sync` or `service_desk` (re-run). |
| workflow_actions | Step in a workflow | `success`, `failed` or `skipped`, with error type and message. |
| data_quality_issues | Rule violation for one employee | Opened by the daily scan, resolved when the rule stops firing. |
| audit_events | Identity-side change | Account, access and session changes. |
| ai_insight_runs | AI request | Sanitized summaries only. |

## Additions to the original specification

Each one fixes a gap that came up while building the simulation:

| Column | Why |
|--------|-----|
| `workflow_runs.requested_at` | A future-dated termination queues offboarding days before it runs. Without a separate queue time, `started_at` would either be wrong for pending work or inflate durations. `started_at` is NULL while a workflow is pending. |
| `workflow_actions.target_name` | Which group, role or license an action applied to. Needed to answer "which licenses fail to be removed" and to investigate a single failure. |
| `sync_runs.skipped_records` | Lets the run totals add up when unchanged records are not stored individually. |
| `sync_runs.error_message` | A run can fail before processing any record (missing HR export, missing column). The reason has to be stored somewhere. |

## Constraints and indexes

- **CHECK constraints** restrict status-style columns (employment status, account status, workflow
  type and status, action type and status, error type, severity) to known values. Free-text HR
  fields such as department and location are deliberately unconstrained: invalid values are
  something the data-quality scan has to find, not something the database should reject.
- **Unique constraints** on `employees.employee_id`, `identity_accounts.username`,
  `identity_accounts.employee_id` and `sync_runs.run_id`. Email is not unique because duplicate
  HR records are part of the data being analysed.
- **Indexes** on the foreign-key columns of every child table. PostgreSQL does not index foreign
  keys automatically, and these are the join and filter paths for the employee investigation
  screen (`WHERE employee_id = ?`) and for run → result joins. At the current volume (a few
  thousand rows per table) the gain is small. No other indexes are added until a query needs one.
