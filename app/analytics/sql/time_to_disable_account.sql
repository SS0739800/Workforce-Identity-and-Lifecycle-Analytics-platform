-- After HR marks someone terminated, how quickly is their account disabled?
-- Employees whose HR status was never changed to terminated are not included here;
-- they appear as 'incorrect_employment_status' data-quality issues instead.
WITH terminations AS (
    SELECT employee_id, max(changed_at) AS terminated_at
    FROM attribute_change_logs
    WHERE attribute_name = 'employment_status'
      AND new_value = 'terminated'
    GROUP BY employee_id
),
timing AS (
    SELECT
        a.account_status,
        extract(epoch FROM a.account_disabled_at - t.terminated_at) / 3600 AS hours_to_disable
    FROM terminations AS t
    JOIN identity_accounts AS a ON a.employee_id = t.employee_id
    WHERE t.terminated_at >= :start_date
      AND t.terminated_at < :end_date
)
SELECT
    count(*)                                                                AS terminated_with_account,
    count(*) FILTER (WHERE account_status = 'active')                       AS still_enabled,
    -- accounts already disabled for a leave of absence before the termination
    count(*) FILTER (WHERE hours_to_disable < 0)                            AS disabled_before_termination,
    count(*) FILTER (WHERE hours_to_disable >= 0 AND hours_to_disable <= 4) AS disabled_within_4_hours,
    count(*) FILTER (WHERE hours_to_disable > 4 AND hours_to_disable <= 24) AS disabled_within_24_hours,
    count(*) FILTER (WHERE hours_to_disable > 24)                           AS disabled_after_24_hours,
    round(
        (percentile_cont(0.5) WITHIN GROUP (ORDER BY hours_to_disable)
            FILTER (WHERE hours_to_disable >= 0))::numeric,
        1
    )                                                                       AS median_hours_to_disable
FROM timing;
