-- Which departments' records fail to sync most often?
-- Uses the employee's current department.
SELECT
    coalesce(e.department, '(blank)')                    AS department,
    count(*)                                             AS sync_attempts,
    count(*) FILTER (WHERE r.status = 'failed')          AS failures,
    round(100.0 * count(*) FILTER (WHERE r.status = 'failed') / count(*), 1)
                                                         AS failure_rate_pct
FROM sync_record_results AS r
JOIN employees AS e ON e.id = r.employee_id
WHERE r.started_at >= :start_date
  AND r.started_at < :end_date
GROUP BY e.department
ORDER BY failures DESC, sync_attempts DESC;
