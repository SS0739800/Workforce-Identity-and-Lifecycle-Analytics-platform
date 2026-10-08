# Report pages

Four pages. Each answers one question, and every visual on it is there to answer that
question. Measures are in [measures.dax](measures.dax); field names are columns of the
reporting views.

## Layout and style rules (all pages)

- 16:9 canvas. Page title top-left with the question as a subtitle in smaller grey text.
- Slicers in a narrow strip on the left, the same on every page: **Date** (`dim_date[date]`,
  "Between" style) and **Department** (`dim_employee[department]`, dropdown). Sync the date
  slicer across pages (View > Sync slicers).
- Cards in one row under the title, at most six. Keep card labels to the measure name.
- One neutral colour for normal values and one accent colour (e.g. dark orange) for failures.
  Use it the same way on every page. No gradients, no background images, no 3D visuals.
- Tables for investigation, charts for trends. Put the unit in the title when it isn't obvious
  ("Average workflow duration (seconds)").
- Turn off visual borders and shadows; use white space between groups.

---

## Page 1: Identity Operations Overview

**Question:** What is happening across identity operations?

| Area | Visual | Fields |
|------|--------|--------|
| Cards | 6 cards | `Active Employees`, `Active Identities`, `Sync Success Rate`, `Workflow Failure Rate`, `Open DQ Issues`, `Leavers With Access Remaining` |
| Top left | Line chart: *Lifecycle activity by month* | X: `dim_date[month_label]` · Y: `Workflow Count` · Legend: `fact_workflow_runs[workflow_type]` |
| Top right | Clustered column: *Failures by month* | X: `dim_date[month_label]` · Y: `Failed Workflows`, `Sync Records Failed` |
| Bottom left | Bar chart: *Workflows by department* | Y: `dim_employee[department]` · X: `Workflow Count` · sorted descending |
| Bottom right | Table: *Leavers with access remaining* | `dim_employee[employee_name]`, `[hr_employee_id]`, `[department]`, `[termination_date]`, `[account_status]` · visual filter: `has_access_after_termination` is True |

Notes:
- `Active Identities` is lower than `Active Employees` because accounts are disabled during leave
  and some new hires are blocked by bad HR data. That gap is worth pointing out, not hiding.
- The leavers table is the highest-risk item on the page: accounts or access that offboarding left behind.

---

## Page 2: Synchronization Analytics

**Question:** Are identity records synchronizing reliably?

Extra slicer: `dim_employee[location]`.

| Area | Visual | Fields |
|------|--------|--------|
| Cards | 5 cards | `Sync Runs`, `Failed Sync Runs`, `Sync Record Attempts`, `Sync Success Rate`, `Avg Sync Run Duration (s)` |
| Top | Line and clustered column: *Sync volume and failures by month* | X: `dim_date[month_label]` · Columns: `Sync Records Updated`, `Sync Records Failed` · Line: `Sync Failure Rate` |
| Middle left | Bar chart: *Why records fail* | Y: `fact_sync_records[error_type]` · X: `Sync Records Failed` |
| Middle right | Matrix: *Department performance* | Rows: `dim_employee[department]` · Values: `Sync Record Attempts`, `Sync Records Failed`, `Sync Failure Rate` (data bars on the rate) |
| Bottom | Table: *Failed runs* | `fact_sync_runs[date]`, `[run_id]`, `[triggered_by]`, `[error_message]` · visual filter: `status` is "failed" |

Notes:
- `Records Evaluated` (every record on every run) is deliberately not a headline card. It is
  large and flat, and it says nothing about reliability. Put it in a tooltip on the monthly chart.
- Run-level measures (`Sync Runs`, `Failed Sync Runs`, durations) don't respond to the
  department or location slicers, because a run covers everyone. Add a small text note
  under the cards saying so.

---

## Page 3: Lifecycle Analytics

**Question:** How reliably do onboarding, offboarding, leave and return workflows complete?

Extra slicer: `dim_workflow_type[workflow_label]` as buttons (tile style). It filters both
workflow runs and workflow actions.

| Area | Visual | Fields |
|------|--------|--------|
| Cards | 6 cards | `Workflow Count`, `Workflow Success Rate`, `First-Time Offboarding Success Rate`, `Avg Workflow Duration (s)`, `Service Desk Reruns`, `Pending Workflows` |
| Top left | Stacked column: *Workflows by month* | X: `dim_date[month_label]` · Y: `Workflow Count` · Legend: `fact_workflow_runs[status]` |
| Top right | Bar chart: *Action failure rate* | Y: `fact_workflow_actions[action_type]` · X: `Action Failure Rate` · tooltip: `Failed Actions`, `Action Attempts` · sorted descending |
| Bottom left | Matrix: *Failed actions by error type* | Rows: `fact_workflow_actions[action_type]` · Columns: `[error_type]` · Values: `Failed Actions` (background colour scale, light to accent) |
| Bottom right | Table: *Pending workflows* | `dim_employee[employee_name]`, `[hr_employee_id]`, `[termination_date]`, `fact_workflow_runs[requested_at_utc]` · visual filter: `status` is "pending" |

Notes:
- Selecting "Offboarding" in the slicer shows which cleanup steps fail. That is the view to
  use when explaining leftover access from Page 1.
- License removal fails more often than group removal because the simulation assumes a less
  reliable licensing API. Say that in a text note: the data shows *that* it happens, not *why*.

---

## Page 4: Data Quality

**Question:** Where does the HR data have problems, and do they affect operations?

| Area | Visual | Fields |
|------|--------|--------|
| Cards | 6 cards | `DQ Issues`, `Open DQ Issues`, `Resolved DQ Issues`, `Open Critical DQ Issues`, `Employees With Open Issues`, `Avg Days to Resolve` |
| Top left | Clustered column: *Found vs fixed by month* | X: `dim_date[month_label]` · Y: `DQ Issues` (by detected date), `Issues Resolved (by resolved date)` |
| Top right | Stacked bar: *Issues by type* | Y: `fact_dq_issues[issue_type]` · X: `DQ Issues` · Legend: `[status]` |
| Middle left | Bar chart: *Issues by field* | Y: `fact_dq_issues[field_name]` · X: `DQ Issues` |
| Middle right | Bar chart: *Issues by department* | Y: `dim_employee[department]` · X: `DQ Issues` |
| Bottom left | Clustered column: *Sync failure rate with and without an open issue* | X: `fact_sync_records[had_open_dq_issue]` · Y: `Sync Failure Rate` · data labels on |
| Bottom right | Table: *Employees with open issues* | `dim_employee[employee_name]`, `[hr_employee_id]`, `[department]`, `[open_dq_issues]` · visual filter: `open_dq_issues` > 0 · sorted by `open_dq_issues` |

Notes:
- `Open DQ Issues` under a date filter means "detected in this period and still open".
  Put that in the card's tooltip.
- Text note under the sync-impact chart: *"Records with an open data-quality issue fail to sync
  far more often. In this synthetic dataset that link is built in, because the sync validates
  the same rules the scan checks, so this shows an association, not a measured cause."*
