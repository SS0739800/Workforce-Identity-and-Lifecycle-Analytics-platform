-- For each license: how often did removal at offboarding fail, and how many are still assigned to leavers?
-- Removal attempts are filtered by date; remaining assignments are current state.
WITH removals AS (
    SELECT
        target_name                                   AS license_name,
        count(*)                                      AS removal_attempts,
        count(*) FILTER (WHERE status = 'failed')     AS removal_failures
    FROM workflow_actions
    WHERE action_type = 'remove_license'
      AND status <> 'skipped'
      AND started_at >= :start_date
      AND started_at < :end_date
    GROUP BY target_name
),
remaining AS (
    SELECT l.license_name, count(*) AS still_assigned_to_terminated
    FROM license_assignments AS l
    JOIN employees AS e ON e.id = l.employee_id
    WHERE l.status = 'active'
      AND e.employment_status = 'terminated'
    GROUP BY l.license_name
)
SELECT
    coalesce(r.license_name, m.license_name)                            AS license_name,
    coalesce(r.removal_attempts, 0)                                     AS removal_attempts,
    coalesce(r.removal_failures, 0)                                     AS removal_failures,
    round(100.0 * r.removal_failures / nullif(r.removal_attempts, 0), 1) AS failure_rate_pct,
    coalesce(m.still_assigned_to_terminated, 0)                         AS still_assigned_to_terminated
FROM removals AS r
FULL OUTER JOIN remaining AS m ON m.license_name = r.license_name
ORDER BY still_assigned_to_terminated DESC, removal_failures DESC, license_name;
