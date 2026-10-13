# AI examples

Captured on 2026-10-13 by `scripts/capture_ai_examples.py` against the synthetic dataset. Each answer is copied exactly as the model returned it, next to the facts it was given (computed by SQL) and the result of the grounding check, which lists any number in the answer that does not appear in the facts. See [ai.md](ai.md) for how the layer works.

Model output varies between runs; re-running the script gives different wording over the same numbers.

## 1. Question mapped to an approved query

**Request:** `POST /api/ai/ask` — "Which departments had the most synchronization failures this quarter?"

**Status:** `ok` · model `openai/gpt-oss-120b` · numbers in the answer that are not in the facts: none

### Facts given to the model

Query `sync_failures_by_department` · this quarter · 10 rows

| department | sync_attempts | failures | failure_rate_pct |
|---|---|---|---|
| Production | 70 | 12 | 17.1 |
| Engineering | 30 | 4 | 13.3 |
| Maintenance | 16 | 4 | 25.0 |
| Finance | 9 | 3 | 33.3 |
| Quality Assurance | 13 | 0 | 0.0 |
| Supply Chain | 8 | 0 | 0.0 |
| Sales | 5 | 0 | 0.0 |
| Human Resources | 4 | 0 | 0.0 |

*…and 2 more rows.*

### Answer (unedited model output)

> **Query used:** *sync_failures_by_department* (this quarter)
>
> **Observed data – highest failure counts**
> - **Production:** 12 failures (17.1 % failure rate) – highest total failures.
> - **Engineering:** 4 failures (13.3 % failure rate) – tied for second‑highest.
> - **Maintenance:** 4 failures (25.0 % failure rate) – tied for second‑highest.
> - **Finance:** 3 failures (33.3 % failure rate).
>
> **Possible focus for investigation**
> - Why Production experiences a markedly higher number of sync failures than other departments.
> - Whether the elevated failure rates in Engineering, Maintenance, and Finance indicate systemic issues despite lower absolute counts.

## 2. Question mapped to an approved query

**Request:** `POST /api/ai/ask` — "What were the most common offboarding failures last month?"

**Status:** `ok` · model `openai/gpt-oss-120b` · numbers in the answer that are not in the facts: none

### Facts given to the model

Query `workflow_action_failures` · last month · 9 rows

| action_type | error_type | failures | employees_affected |
|---|---|---|---|
| remove_license | DEPENDENCY_ERROR | 3 | 3 |
| remove_group_membership | TIMEOUT | 2 | 2 |
| reset_password | TIMEOUT | 2 | 2 |
| remove_license | TIMEOUT | 1 | 1 |
| remove_role | PERMISSION_ERROR | 1 | 1 |
| remove_role | TIMEOUT | 1 | 1 |
| reset_password | VALIDATION_ERROR | 1 | 1 |
| revoke_session | DEPENDENCY_ERROR | 1 | 1 |

*…and 1 more rows.*

### Answer (unedited model output)

> **Query used:** workflow_action_failures (offboarding, last month)
>
> **Observed most frequent failures**
> - **Action:** `remove_license` – **Error:** `DEPENDENCY_ERROR` – **Failures:** 3 (3 employees affected)  
> - Next‑most frequent (tied):  
>   - `remove_group_membership` – `TIMEOUT` – 2 failures  
>   - `reset_password` – `TIMEOUT` – 2 failures  
>
> **Possible explanations to investigate**
> - Dependency chains that block license removal (e.g., lingering assignments or pending provisioning).  
> - System latency or connectivity issues causing timeouts for group membership removal and password resets.  
>
> Further analysis of dependency logs and timeout patterns could clarify root causes.

## 3. Question outside the approved queries

**Request:** `POST /api/ai/ask` — "What is the CEO's home address?"

**Status:** `unmatched` · model `none` · numbers in the answer that are not in the facts: none

### Facts given to the model

```json
{
  "answered": false,
  "example_questions": [
    "Which departments had the most synchronization failures this quarter?",
    "What were the most common offboarding failures last month?",
    "Why do sync records fail?",
    "Which licenses fail to be removed at offboarding?",
    "What are the most common data-quality issues?",
    "How quickly are accounts disabled after termination?"
  ]
}
```

### Answer (unedited model output)

> This question doesn't match an approved query. Try one of the examples.

## 4. Failure explanation

**Request:** `POST /api/ai/failure-explanation` — "Why are license removal failures higher than group removal failures?"

**Status:** `ok` · model `openai/gpt-oss-120b` · numbers in the answer that are not in the facts: none

### Facts given to the model

```json
{
  "action_failure_rates": [
    {
      "action_type": "remove_license",
      "attempts": 164,
      "failures": 17,
      "skipped": 0,
      "failure_rate_pct": 10.4
    },
    {
      "action_type": "assign_license",
      "attempts": 186,
      "failures": 12,
      "skipped": 6,
      "failure_rate_pct": 6.5
    },
    {
      "action_type": "reset_password",
      "attempts": 115,
      "failures": 5,
      "skipped": 0,
      "failure_rate_pct": 4.3
    },
    {
      "action_type": "remove_role",
      "attempts": 120,
      "failures": 5,
      "skipped": 0,
      "failure_rate_pct": 4.2
    },
    {
      "action_type": "create_account",
      "attempts": 127,
      "failures": 4,
      "skipped": 0,
      "failure_rate_pct": 3.1
    },
    {
      "action_type": "remove_group_membership",
      "attempts": 398,
      "failures": 12,
      "skipped": 0,
      "failure_rate_pct": 3.0
    },
    {
      "action_type": "enable_account",
      "attempts": 45,
      "failures": 1,
      "skipped": 0,
      "failure_rate_pct": 2.2
    },
    {
      "action_type": "disable_account",
      "attempts": 155,
      "failures": 3,
      "skipped": 20,
      "failure_rate_pct": 1.9
    },
    {
      "action_type": "revoke_session",
      "attempts": 175,
      "failures": 3,
      "skipped": 0,
      "failure_rate_pct": 1.7
    },
    {
      "action_type": "add_group_membership",
      "attempts": 432,
      "failures": 5,
      "skipped": 14,
      "failure_rate_pct": 1.2
    },
    {
      "action_type": "update_attribute",
      "attempts": 105,
      "failures": 1,
      "skipped": 0,
      "failure_rate_pct": 1.0
    },
    {
      "action_type": "assign_role",
      "attempts": 125,
      "failures": 1,
      "skipped": 4,
      "failure_rate_pct": 0.8
    }
  ],
  "failures_by_action_and_error_type": [
    {
      "action_type": "assign_license",
      "error_type": "DEPENDENCY_ERROR",
      "failures": 10
    },
    {
      "action_type": "remove_license",
      "error_type": "DEPENDENCY_ERROR",
      "failures": 10
    },
    {
      "action_type": "remove_group_membership",
      "error_type": "TIMEOUT",
      "failures": 8
    },
    {
      "action_type": "remove_license",
      "error_type": "TIMEOUT",
      "failures": 7
    },
    {
      "action_type": "add_group_membership",
      "error_type": "RESOURCE_NOT_FOUND",
      "failures": 3
    },
    {
      "action_type": "create_account",
      "error_type": "TIMEOUT",
      "failures": 3
…(truncated)
```

### Answer (unedited model output)

> **Observed**  
> - **Remove license** – 164 attempts, 17 failures → failure rate **10.4 %**.  
>   - Errors: 10 × DEPENDENCY_ERROR, 7 × TIMEOUT (total 17).  
> - **Remove group membership** – 398 attempts, 12 failures → failure rate **3.0 %**.  
>   - Errors: 8 × TIMEOUT, 2 × PERMISSION_ERROR, 2 × RESOURCE_NOT_FOUND (total 12).  
>
> **What the data does not show**  
> - The records provide counts and error categories only; they do not explain *why* license‑removal actions encounter more failures than group‑removal actions. No information on underlying system state, data quality, or external dependencies is included.
>
> **Possible areas to investigate**  
> 1. **Dependency chain for license removal** – the high number of DEPENDENCY_ERRORs (10) suggests a downstream service or prerequisite may be failing; verify the health and latency of any license‑provisioning APIs.  
> 2. **Timeout handling differences** – both actions see TIMEOUTs, but license removal has 7 versus 8 for group removal despite fewer attempts; check if license removal calls have longer execution windows or stricter timeout settings.  
> 3. **Permission and resource validation** – group‑removal failures include PERMISSION_ERROR and RESOURCE_NOT_FOUND, while license removal does not; assess whether license removal bypasses certain checks that could mask other root causes.

## 5. Monthly summary

**Request:** `POST /api/ai/executive-summary?month=2026-09`

**Status:** `ok` · model `openai/gpt-oss-120b` · numbers in the answer that are not in the facts: none

### Facts given to the model

```json
{
  "month": "September 2026",
  "sync_runs": 30,
  "sync_records_processed": 45,
  "sync_success_rate_pct": 95.6,
  "offboarding_workflows": 9,
  "workflows": 28,
  "workflow_failure_rate_pct": 11.5,
  "most_common_failure": {
    "action_type": "create_account",
    "error_type": "TIMEOUT",
    "failures": 1
  },
  "open_data_quality_issues_now": 36,
  "department_with_most_sync_failures": {
    "department": "Production",
    "failures": 1
  }
}
```

### Answer (unedited model output)

> **September 2026 Identity Operations Summary**
>
> - Sync volume: 45 records processed  
> - Sync success rate: 95.6 %  
> - Off‑boarding volume: 9 workflows  
> - Workflow failure rate: 11.5 %  
> - Most common failure: create_account – TIMEOUT (1 occurrence)  
> - Open data‑quality issues: 36  
> - Most affected department: Production (1 failure)  
>
> The sync process remains highly reliable, but the 11.5 % workflow failure rate and the single TIMEOUT on account creation suggest a need to review timeout handling. The concentration of failures in Production, albeit low, may warrant targeted monitoring.

## 6. Data-quality explanation

**Request:** `POST /api/ai/data-quality-explanation`

**Status:** `ok` · model `openai/gpt-oss-120b` · numbers in the answer that are not in the facts: none

### Facts given to the model

```json
{
  "summary": {
    "total_issues": 93,
    "open_issues": 36,
    "resolved_issues": 57,
    "open_critical_issues": 1,
    "employees_with_open_issues": 29,
    "avg_days_to_resolve": 20.1
  },
  "by_type": [
    {
      "issue_type": "missing_identity_account",
      "field_name": "identity_account",
      "severity": "high",
      "issues": 17,
      "open_issues": 6,
      "resolved_issues": 11,
      "avg_days_to_resolve": 27.1
    },
    {
      "issue_type": "license_on_inactive_employee",
      "field_name": "license_assignment",
      "severity": "medium",
      "issues": 15,
      "open_issues": 6,
      "resolved_issues": 9,
      "avg_days_to_resolve": 3.2
    },
    {
      "issue_type": "stale_group_membership",
      "field_name": "group_membership",
      "severity": "medium",
      "issues": 12,
      "open_issues": 6,
      "resolved_issues": 6,
      "avg_days_to_resolve": 2.7
    },
    {
      "issue_type": "invalid_location",
      "field_name": "location",
      "severity": "low",
      "issues": 11,
      "open_issues": 2,
      "resolved_issues": 9,
      "avg_days_to_resolve": 38.8
    },
    {
      "issue_type": "invalid_email",
      "field_name": "email",
      "severity": "high",
      "issues": 7,
      "open_issues": 2,
      "resolved_issues": 5,
      "avg_days_to_resolve": 48.0
    },
    {
      "issue_type": "missing_termination_date",
      "field_name": "termination_date",
      "severity": "medium",
      "issues": 7,
      "open_issues": 2,
      "resolved_issues": 5,
      "avg_days_to_resolve": 15.4
    },
    {
      "issue_type": "stale_role_assignment",
      "field_name": "role_assignment",
      "severity": "high",
      "issues": 5,
      "open_issues": 3,
      "resolved_issues": 2,
      "avg_days_to_resolve": 4.0
    },
    {
      "issue_type": "invalid_department",
      "field_name": "department",
      "severity": "medium",
      "issues": 4,
      "open_issues": 3,
      "resolved_issues": 1,
      "avg_days_to_resolve": 19.0
    },
    {
      "issue_type": "missing_employee_id",
      "field_name": "employee_id",
      "severity": "high",
      "issues": 4,
      "open_issues": 1,
      "resolved_issues": 3,
      "avg_days_to_resolve": 14.7
    },
    {
      "issue_type": "missing_manager",
      "field_name": "manager_id",
      "severity": "medium",
      "issues": 4,
      "open_issues": 1,
      "resolved_issues": 3,
      "avg_days_to_resolve": 12.3
    },
    {
      "issue_type": "dupli
…(truncated)
```

### Answer (unedited model output)

> **Key data‑quality problems (observed)**  
>
> - **Highest‑volume issue types**  
>   - *missing_identity_account* (field = identity_account): 17 total, 6 open – severity high.  
>   - *license_on_inactive_employee* (license_assignment): 15 total, 6 open – severity medium.  
>   - *stale_group_membership* (group_membership): 12 total, 6 open – severity medium.  
>   - *invalid_location* (location): 11 total, 2 open – severity low.  
>
> - **High‑severity / critical issues**  
>   - *missing_identity_account* – 17 issues (high).  
>   - *invalid_email* (email): 7 issues, 2 open – severity high.  
>   - *stale_role_assignment* (role_assignment): 5 issues, 3 open – severity high.  
>   - *missing_employee_id* (employee_id): 4 issues, 1 open – severity high.  
>   - *duplicate_employee* (employee_record): 3 issues, **all 3 open** – severity high.  
>   - *active_account_for_terminated_employee* (account_status): 2 issues, both resolved – severity critical.  
>   - *incorrect_employment_status* (employment_status): 1 issue, still open – severity critical.  
>
> - **Departments with the most issues**  
>   - **Production**: 42 issues (7 open), affecting 24 employees.  
>   - **Engineering**: 14 issues (9 open), affecting 12 employees.  
>   - **Maintenance**: 10 issues (6 open), affecting 8 employees.  
>
> - **Open‑issue concentration**  
>   - 36 open issues across 29 employees.  
>   - Open issues are most common in Engineering (9), Maintenance (6), and Production (7).  
>
> **Association between open issues and sync failures (observed)**  
>
> - When a record had an open issue: 82 sync attempts, 69 failures → **84.1 % failure rate**.  
> - When a record had no open issue: 687 sync attempts, 10 failures → **1.5 % failure rate**.  
>
> *Interpretation to investigate*  
> - The sync process validates the same rules that the scan flags; the markedly higher failure rate for records with open issues suggests a strong association.  
> - Possible investigation points: whether the sync engine is correctly handling records flagged by the scan, or if remediation of open issues reduces sync failures.  
>
> *Operational take‑aways*  
> - Prioritise resolution of high‑severity open issues (especially duplicate_employee, stale_role_assignment, and missing_identity_account) to potentially improve sync success.  
> - Focus remediation effort on Engineering and Production where open‑issue density is highest.

## 7. Incident report for a failed offboarding

**Request:** `POST /api/ai/incident-report/23`

**Status:** `ok` · model `openai/gpt-oss-120b` · numbers in the answer that are not in the facts: none

### Facts given to the model

```json
{
  "workflow": {
    "workflow_run_id": 23,
    "workflow_type": "offboarding",
    "status": "failed",
    "initiated_by": "nightly_sync",
    "requested_at": "2025-11-05T02:00:36Z",
    "started_at": "2025-11-22T02:01:35Z",
    "completed_at": "2025-11-22T02:02:26Z"
  },
  "employee": {
    "hr_employee_id": "EMP00745",
    "department": "Customer Service",
    "job_title": "Customer Service Representative",
    "location": "Remote",
    "employment_status": "terminated"
  },
  "timeline": [
    {
      "action_type": "disable_account",
      "target": null,
      "status": "success",
      "started_at": "2025-11-22T02:01:35Z",
      "completed_at": "2025-11-22T02:01:36Z",
      "error_type": null
    },
    {
      "action_type": "revoke_session",
      "target": null,
      "status": "success",
      "started_at": "2025-11-22T02:01:37Z",
      "completed_at": "2025-11-22T02:01:38Z",
      "error_type": null
    },
    {
      "action_type": "reset_password",
      "target": null,
      "status": "success",
      "started_at": "2025-11-22T02:01:40Z",
      "completed_at": "2025-11-22T02:01:44Z",
      "error_type": null
    },
    {
      "action_type": "remove_group_membership",
      "target": "All Staff",
      "status": "success",
      "started_at": "2025-11-22T02:01:45Z",
      "completed_at": "2025-11-22T02:01:49Z",
      "error_type": null
    },
    {
      "action_type": "remove_group_membership",
      "target": "DEPT-CS",
      "status": "success",
      "started_at": "2025-11-22T02:01:50Z",
      "completed_at": "2025-11-22T02:01:56Z",
      "error_type": null
    },
    {
      "action_type": "remove_group_membership",
      "target": "SITE-REM",
      "status": "success",
      "started_at": "2025-11-22T02:01:58Z",
      "completed_at": "2025-11-22T02:02:05Z",
      "error_type": null
    },
    {
      "action_type": "remove_group_membership",
      "target": "VPN Users",
      "status": "success",
      "started_at": "2025-11-22T02:02:05Z",
      "completed_at": "2025-11-22T02:02:06Z",
      "error_type": null
    },
    {
      "action_type": "remove_role",
      "target": "CRM Service Agent",
      "status": "failed",
      "started_at": "2025-11-22T02:02:07Z",
      "completed_at": "2025-11-22T02:02:12Z",
      "error_type": "PERMISSION_ERROR"
    },
    {
      "action_type": "remove_license",
      "target": "Office Suite Standard",
      "status": "success",
      "started_at": "2025-11-22T02:02:12Z",
      "completed_at": "2025-
…(truncated)
```

### Answer (unedited model output)

> **Summary**  
> - Offboarding workflow run #23 failed.  
> - Initiated by *nightly_sync* on 2025‑11‑05 02:00:36 UTC.  
> - Execution started 2025‑11‑22 02:01:35 UTC and completed 2025‑11‑22 02:02:26 UTC.  
> - Failure caused by a *remove_role* action returning a **PERMISSION_ERROR**.
>
> **Workflow**  
> - Workflow ID: 23  
> - Type: offboarding  
> - Initiated by: nightly_sync  
> - Requested at: 2025‑11‑05 02:00:36 +00:00  
> - Started at: 2025‑11‑22 02:01:35 +00:00  
> - Completed at: 2025‑11‑22 02:02:26 +00:00  
> - Overall status: failed  
>
> **Failed action(s)**  
> - **Action:** remove_role – target **CRM Service Agent**  
> - **Error type:** PERMISSION_ERROR  
> - **Error message:** “Service account cannot remove role 'CRM Service Agent'”
>
> **Timeline**  
>
> | Time (UTC) | Action | Target | Status | Error type |
> |------------|--------|--------|--------|------------|
> | 02:01:35 – 02:01:36 | disable_account | – | success | – |
> | 02:01:37 – 02:01:38 | revoke_session | – | success | – |
> | 02:01:40 – 02:01:44 | reset_password | – | success | – |
> | 02:01:45 – 02:01:49 | remove_group_membership | All Staff | success | – |
> | 02:01:50 – 02:01:56 | remove_group_membership | DEPT‑CS | success | – |
> | 02:01:58 – 02:02:05 | remove_group_membership | SITE‑REM | success | – |
> | 02:02:05 – 02:02:06 | remove_group_membership | VPN Users | success | – |
> | 02:02:07 – 02:02:12 | **remove_role** | **CRM Service Agent** | **failed** | **PERMISSION_ERROR** |
> | 02:02:12 – 02:02:20 | remove_license | Office Suite Standard | success | – |
> | 02:02:20 – 02:02:26 | remove_license | CRM Seat | success | – |
>
> **Observed impact (current)**  
> - Account status: **disabled**  
> - Active groups: **0**  
> - Active roles: **1** (CRM Service Agent remains)  
> - Active licenses: **0**  
>
> **Historical context**  
> - Failure rate for *remove_role* actions: **4.2 %** overall.  
> - PERMISSION_ERROR occurrences in the prior 30 days: **0**.  
> - Service‑desk reruns after this failure: **0** (no reruns recorded).  
> - No other workflows or failed workflows exist for employee **EMP00745**.  
>
> **Potential investigation areas** *(things to explore, not conclusions)*  
> - Verify the automation (service) account’s rights to modify or remove the **CRM Service Agent** role.  
> - Review role‑management policies that may restrict privileged role removal by service accounts.  
> - Check for recent changes to role permission assignments that could affect automation access.  
> - Confirm that the target role object has not been locked or protected inadvertently.
