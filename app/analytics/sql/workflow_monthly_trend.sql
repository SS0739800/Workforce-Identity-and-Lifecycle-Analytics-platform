-- How does workflow volume and failure change month by month?
SELECT
    date_trunc('month', requested_at AT TIME ZONE 'UTC')::date  AS month,
    workflow_type,
    count(*)                                                    AS workflows,
    count(*) FILTER (WHERE status = 'failed')                   AS failed
FROM workflow_runs
WHERE requested_at >= :start_date
  AND requested_at < :end_date
GROUP BY month, workflow_type
ORDER BY month, workflow_type;
