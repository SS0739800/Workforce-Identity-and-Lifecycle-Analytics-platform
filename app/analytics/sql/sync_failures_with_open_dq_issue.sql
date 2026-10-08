-- Do records with an open data-quality issue fail to sync more often?
-- This shows an association, not a cause. In this synthetic dataset the link is built in,
-- because the sync validates the same rules the data-quality scan checks.
WITH attempts AS (
    SELECT
        r.status,
        EXISTS (
            SELECT 1
            FROM data_quality_issues AS d
            WHERE d.employee_id = r.employee_id
              AND d.detected_at <= r.started_at
              AND (d.resolved_at IS NULL OR d.resolved_at > r.started_at)
        ) AS had_open_issue
    FROM sync_record_results AS r
    WHERE r.started_at >= :start_date
      AND r.started_at < :end_date
)
SELECT
    had_open_issue,
    count(*)                                     AS sync_attempts,
    count(*) FILTER (WHERE status = 'failed')    AS failures,
    round(100.0 * count(*) FILTER (WHERE status = 'failed') / count(*), 1) AS failure_rate_pct
FROM attempts
GROUP BY had_open_issue
ORDER BY had_open_issue DESC;
