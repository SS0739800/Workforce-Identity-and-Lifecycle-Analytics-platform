-- Totals the Power BI report should show with no filters applied.
-- Run against the same database the report reads:
--   docker compose exec -T postgres psql -U workforce -d workforce < powerbi/validation.sql
-- Each column is named after the DAX measure it checks. Rates are percentages here;
-- in Power BI they are fractions formatted as percentages.

\echo '--- Workforce'
SELECT
    count(*)                                                       AS "Total Employees",
    count(*) FILTER (WHERE employment_status = 'active')           AS "Active Employees",
    count(*) FILTER (WHERE account_status = 'active')              AS "Active Identities",
    count(*) FILTER (WHERE has_access_after_termination)           AS "Leavers With Access Remaining"
FROM reporting.dim_employee;

\echo '--- Synchronization'
SELECT
    (SELECT count(*) FROM reporting.fact_sync_runs)                                    AS "Sync Runs",
    (SELECT count(*) FROM reporting.fact_sync_runs WHERE status = 'failed')            AS "Failed Sync Runs",
    (SELECT sum(total_records) FROM reporting.fact_sync_runs)                          AS "Records Evaluated",
    count(*)                                                                           AS "Sync Record Attempts",
    count(*) FILTER (WHERE status = 'failed')                                          AS "Sync Records Failed",
    round(100.0 * count(*) FILTER (WHERE status = 'success') / count(*), 1)           AS "Sync Success Rate %",
    (SELECT round(avg(duration_seconds), 1) FROM reporting.fact_sync_runs)             AS "Avg Sync Run Duration (s)"
FROM reporting.fact_sync_records;

\echo '--- Lifecycle workflows'
SELECT
    count(*)                                                                           AS "Workflow Count",
    count(*) FILTER (WHERE status = 'completed')                                       AS "Completed Workflows",
    count(*) FILTER (WHERE status = 'failed')                                          AS "Failed Workflows",
    count(*) FILTER (WHERE status = 'pending')                                         AS "Pending Workflows",
    round(100.0 * count(*) FILTER (WHERE status = 'failed')
          / count(*) FILTER (WHERE status IN ('completed', 'failed')), 1)              AS "Workflow Failure Rate %",
    count(*) FILTER (WHERE is_rerun)                                                   AS "Service Desk Reruns",
    round(avg(duration_seconds), 1)                                                    AS "Avg Workflow Duration (s)",
    round(100.0 * count(*) FILTER (WHERE workflow_type = 'offboarding' AND NOT is_rerun AND status = 'completed')
          / count(*) FILTER (WHERE workflow_type = 'offboarding' AND NOT is_rerun AND status IN ('completed', 'failed')), 1)
                                                                                       AS "First-Time Offboarding Success Rate %"
FROM reporting.fact_workflow_runs;

SELECT
    count(*) FILTER (WHERE is_attempt)                                                 AS "Action Attempts",
    count(*) FILTER (WHERE status = 'failed')                                          AS "Failed Actions",
    round(100.0 * count(*) FILTER (WHERE status = 'failed') / count(*) FILTER (WHERE is_attempt), 1)
                                                                                       AS "Action Failure Rate %"
FROM reporting.fact_workflow_actions;

\echo '--- Data quality'
SELECT
    count(*)                                                                           AS "DQ Issues",
    count(*) FILTER (WHERE status = 'open')                                            AS "Open DQ Issues",
    count(*) FILTER (WHERE status = 'resolved')                                        AS "Resolved DQ Issues",
    count(*) FILTER (WHERE status = 'open' AND severity = 'critical')                  AS "Open Critical DQ Issues",
    count(DISTINCT employee_key) FILTER (WHERE status = 'open')                        AS "Employees With Open Issues",
    round(avg(days_to_resolve), 1)                                                     AS "Avg Days to Resolve"
FROM reporting.fact_dq_issues;

\echo '--- Sync failure rate by open data-quality issue (Data Quality page)'
SELECT
    had_open_dq_issue,
    count(*)                                                                           AS "Sync Record Attempts",
    round(100.0 * count(*) FILTER (WHERE status = 'failed') / count(*), 1)            AS "Sync Failure Rate %"
FROM reporting.fact_sync_records
GROUP BY had_open_dq_issue
ORDER BY had_open_dq_issue DESC;

\echo '--- Attribute changes'
SELECT
    count(*)                                                                           AS "Attribute Changes",
    count(*) FILTER (WHERE is_correction)                                              AS "Data Corrections"
FROM reporting.fact_attribute_changes;
