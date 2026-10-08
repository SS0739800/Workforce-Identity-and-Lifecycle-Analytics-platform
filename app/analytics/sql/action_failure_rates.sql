-- Which workflow actions fail most often?
-- Skipped actions (already disabled, or not attempted after an earlier failure) are not attempts.
SELECT
    a.action_type,
    count(*) FILTER (WHERE a.status <> 'skipped')    AS attempts,
    count(*) FILTER (WHERE a.status = 'failed')      AS failures,
    count(*) FILTER (WHERE a.status = 'skipped')     AS skipped,
    round(
        100.0 * count(*) FILTER (WHERE a.status = 'failed')
        / nullif(count(*) FILTER (WHERE a.status <> 'skipped'), 0),
        1
    )                                                AS failure_rate_pct
FROM workflow_actions AS a
WHERE a.started_at >= :start_date
  AND a.started_at < :end_date
GROUP BY a.action_type
ORDER BY failure_rate_pct DESC NULLS LAST, failures DESC;
