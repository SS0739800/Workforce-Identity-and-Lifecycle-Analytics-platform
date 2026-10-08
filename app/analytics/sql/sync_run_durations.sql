-- How long do sync runs take, scheduled vs manual?
WITH durations AS (
    SELECT
        triggered_by,
        extract(epoch FROM completed_at - started_at) AS seconds
    FROM sync_runs
    WHERE completed_at IS NOT NULL
      AND started_at >= :start_date
      AND started_at < :end_date
)
SELECT
    triggered_by,
    count(*)                                                               AS runs,
    round(avg(seconds), 1)                                                 AS avg_seconds,
    round(percentile_cont(0.9) WITHIN GROUP (ORDER BY seconds)::numeric, 1) AS p90_seconds,
    round(max(seconds), 1)                                                 AS max_seconds
FROM durations
GROUP BY triggered_by
ORDER BY triggered_by;
