-- Which actions failed in one type of workflow, and with what error?
SELECT
    a.action_type,
    a.error_type,
    count(*)                        AS failures,
    count(DISTINCT w.employee_id)   AS employees_affected
FROM workflow_actions AS a
JOIN workflow_runs AS w ON w.id = a.workflow_run_id
WHERE a.status = 'failed'
  AND w.workflow_type = :workflow_type
  AND a.started_at >= :start_date
  AND a.started_at < :end_date
GROUP BY a.action_type, a.error_type
ORDER BY failures DESC, a.action_type, a.error_type;
