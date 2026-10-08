-- For each failing action, what kind of error is it?
SELECT
    action_type,
    error_type,
    count(*) AS failures
FROM workflow_actions
WHERE status = 'failed'
  AND started_at >= :start_date
  AND started_at < :end_date
GROUP BY action_type, error_type
ORDER BY failures DESC, action_type, error_type;
