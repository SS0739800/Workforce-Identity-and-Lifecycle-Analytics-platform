-- How many lifecycle workflows ran, and how many succeeded?
-- Success rate is completed / (completed + failed); pending workflows have not run yet.
SELECT
    workflow_type,
    count(*)                                         AS workflows,
    count(*) FILTER (WHERE status = 'completed')     AS completed,
    count(*) FILTER (WHERE status = 'failed')        AS failed,
    count(*) FILTER (WHERE status = 'pending')       AS pending,
    count(*) FILTER (WHERE initiated_by = 'service_desk') AS service_desk_reruns,
    round(
        100.0 * count(*) FILTER (WHERE status = 'completed')
        / nullif(count(*) FILTER (WHERE status IN ('completed', 'failed')), 0),
        1
    )                                                AS success_rate_pct
FROM workflow_runs
WHERE requested_at >= :start_date
  AND requested_at < :end_date
GROUP BY workflow_type
ORDER BY workflows DESC;
