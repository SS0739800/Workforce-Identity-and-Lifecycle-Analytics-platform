-- Do sync failures cluster at particular sites?
SELECT
    coalesce(e.location, '(blank)')                      AS location,
    count(*)                                             AS sync_attempts,
    count(*) FILTER (WHERE r.status = 'failed')          AS failures,
    count(*) FILTER (WHERE r.error_type = 'TIMEOUT')     AS timeouts,
    round(100.0 * count(*) FILTER (WHERE r.status = 'failed') / count(*), 1)
                                                         AS failure_rate_pct
FROM sync_record_results AS r
JOIN employees AS e ON e.id = r.employee_id
WHERE r.started_at >= :start_date
  AND r.started_at < :end_date
GROUP BY e.location
ORDER BY failures DESC, sync_attempts DESC;
