-- Which employees keep running into failures, across both the sync and workflows?
WITH failures AS (
    SELECT employee_id, 'sync' AS source, error_type, started_at
    FROM sync_record_results
    WHERE status = 'failed'
    UNION ALL
    SELECT w.employee_id, 'workflow', a.error_type, a.started_at
    FROM workflow_actions AS a
    JOIN workflow_runs AS w ON w.id = a.workflow_run_id
    WHERE a.status = 'failed'
)
SELECT
    e.id                                                AS employee_db_id,
    e.employee_id,
    e.first_name || ' ' || e.last_name                  AS employee_name,
    e.department,
    e.employment_status,
    count(*)                                            AS total_failures,
    count(*) FILTER (WHERE f.source = 'sync')           AS sync_failures,
    count(*) FILTER (WHERE f.source = 'workflow')       AS workflow_failures,
    string_agg(DISTINCT f.error_type, ', ')             AS error_types
FROM failures AS f
JOIN employees AS e ON e.id = f.employee_id
WHERE f.started_at >= :start_date
  AND f.started_at < :end_date
GROUP BY e.id
HAVING count(*) >= :min_failures
ORDER BY total_failures DESC, e.id
LIMIT :limit;
