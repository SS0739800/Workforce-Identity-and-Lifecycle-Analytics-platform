-- How long does each type of workflow take to run (start to finish)?
WITH durations AS (
    SELECT
        workflow_type,
        extract(epoch FROM completed_at - started_at) AS seconds
    FROM workflow_runs
    WHERE completed_at IS NOT NULL
      AND started_at >= :start_date
      AND started_at < :end_date
)
SELECT
    workflow_type,
    count(*)                                                                AS workflows,
    round(avg(seconds), 1)                                                  AS avg_seconds,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds)::numeric, 1) AS median_seconds,
    round(percentile_cont(0.9) WITHIN GROUP (ORDER BY seconds)::numeric, 1) AS p90_seconds
FROM durations
GROUP BY workflow_type
ORDER BY workflow_type;
