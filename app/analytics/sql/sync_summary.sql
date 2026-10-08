-- How reliable was the HR -> identity sync over the period?
-- Record success rate only counts records that needed an update (skipped records are excluded).
SELECT
    count(*)                                                 AS total_runs,
    count(*) FILTER (WHERE status = 'completed')             AS clean_runs,
    count(*) FILTER (WHERE status = 'completed_with_errors') AS runs_with_errors,
    count(*) FILTER (WHERE status = 'failed')                AS failed_runs,
    coalesce(sum(total_records), 0)                          AS records_evaluated,
    coalesce(sum(successful_records), 0)                     AS records_updated,
    coalesce(sum(failed_records), 0)                         AS records_failed,
    round(
        100.0 * sum(successful_records)
        / nullif(sum(successful_records) + sum(failed_records), 0),
        1
    )                                                        AS record_success_rate_pct,
    round(100.0 * count(*) FILTER (WHERE status = 'failed') / nullif(count(*), 0), 1)
                                                             AS run_failure_rate_pct
FROM sync_runs
WHERE started_at >= :start_date
  AND started_at < :end_date;
