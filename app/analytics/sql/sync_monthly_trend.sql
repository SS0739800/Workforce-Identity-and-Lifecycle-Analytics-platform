-- How did sync volume and failures change month by month?
SELECT
    date_trunc('month', started_at AT TIME ZONE 'UTC')::date AS month,
    count(*)                                                  AS runs,
    count(*) FILTER (WHERE status = 'failed')                 AS failed_runs,
    sum(successful_records)                                   AS records_updated,
    sum(failed_records)                                       AS records_failed,
    round(
        100.0 * sum(failed_records)
        / nullif(sum(successful_records) + sum(failed_records), 0),
        1
    )                                                         AS record_failure_rate_pct
FROM sync_runs
WHERE started_at >= :start_date
  AND started_at < :end_date
GROUP BY month
ORDER BY month;
