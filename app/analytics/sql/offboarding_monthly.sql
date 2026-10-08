-- How many offboardings ran each month, and how many needed a service-desk re-run?
-- A first attempt is one started by a sync run (scheduled or manual); re-runs come from the service desk.
SELECT
    date_trunc('month', started_at AT TIME ZONE 'UTC')::date       AS month,
    count(*) FILTER (WHERE initiated_by <> 'service_desk')          AS offboardings,
    count(*) FILTER (WHERE initiated_by <> 'service_desk' AND status = 'completed')
                                                                   AS completed_first_time,
    count(*) FILTER (WHERE initiated_by <> 'service_desk' AND status = 'failed')
                                                                   AS failed_first_time,
    count(*) FILTER (WHERE initiated_by = 'service_desk')          AS service_desk_reruns,
    round(
        100.0 * count(*) FILTER (WHERE initiated_by <> 'service_desk' AND status = 'completed')
        / nullif(count(*) FILTER (WHERE initiated_by <> 'service_desk'), 0),
        1
    )                                                              AS first_time_success_pct
FROM workflow_runs
WHERE workflow_type = 'offboarding'
  AND started_at >= :start_date
  AND started_at < :end_date
GROUP BY month
ORDER BY month;
