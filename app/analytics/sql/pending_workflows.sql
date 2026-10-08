-- Which workflows are queued and waiting to run? (current state, no date filter)
SELECT
    w.id                                 AS workflow_run_id,
    w.workflow_type,
    w.requested_at,
    e.id                                 AS employee_db_id,
    e.employee_id,
    e.first_name || ' ' || e.last_name   AS employee_name,
    e.department,
    e.termination_date
FROM workflow_runs AS w
JOIN employees AS e ON e.id = w.employee_id
WHERE w.status = 'pending'
ORDER BY e.termination_date, w.requested_at;
