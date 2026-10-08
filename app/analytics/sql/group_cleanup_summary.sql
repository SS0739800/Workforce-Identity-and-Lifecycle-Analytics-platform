-- For each group: how often did removal at offboarding fail, and how many leavers are still members?
-- Removal attempts are filtered by date; remaining memberships are current state.
WITH removals AS (
    SELECT
        target_name                                   AS group_name,
        count(*)                                      AS removal_attempts,
        count(*) FILTER (WHERE status = 'failed')     AS removal_failures
    FROM workflow_actions
    WHERE action_type = 'remove_group_membership'
      AND status <> 'skipped'
      AND started_at >= :start_date
      AND started_at < :end_date
    GROUP BY target_name
),
remaining AS (
    SELECT g.group_name, count(*) AS still_assigned_to_terminated
    FROM group_memberships AS g
    JOIN employees AS e ON e.id = g.employee_id
    WHERE g.status = 'active'
      AND e.employment_status = 'terminated'
    GROUP BY g.group_name
)
SELECT
    coalesce(r.group_name, m.group_name)                                AS group_name,
    coalesce(r.removal_attempts, 0)                                     AS removal_attempts,
    coalesce(r.removal_failures, 0)                                     AS removal_failures,
    round(100.0 * r.removal_failures / nullif(r.removal_attempts, 0), 1) AS failure_rate_pct,
    coalesce(m.still_assigned_to_terminated, 0)                         AS still_assigned_to_terminated
FROM removals AS r
FULL OUTER JOIN remaining AS m ON m.group_name = r.group_name
ORDER BY still_assigned_to_terminated DESC, removal_failures DESC, group_name;
