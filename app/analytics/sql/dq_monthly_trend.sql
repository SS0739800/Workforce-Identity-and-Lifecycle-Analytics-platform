-- Are data-quality issues being found faster than they are fixed?
WITH events AS (
    SELECT date_trunc('month', detected_at AT TIME ZONE 'UTC')::date AS month, 1 AS detected, 0 AS resolved
    FROM data_quality_issues
    UNION ALL
    SELECT date_trunc('month', resolved_at AT TIME ZONE 'UTC')::date, 0, 1
    FROM data_quality_issues
    WHERE resolved_at IS NOT NULL
)
SELECT
    month,
    sum(detected) AS detected,
    sum(resolved) AS resolved
FROM events
WHERE month >= date_trunc('month', :start_date)
  AND month < :end_date
GROUP BY month
ORDER BY month;
