-- Which terminated employees still have an enabled account or any access? (current state)
WITH active_access AS (
    SELECT employee_id, 'group' AS kind FROM group_memberships WHERE status = 'active'
    UNION ALL
    SELECT employee_id, 'role' FROM role_assignments WHERE status = 'active'
    UNION ALL
    SELECT employee_id, 'license' FROM license_assignments WHERE status = 'active'
),
access_counts AS (
    SELECT
        employee_id,
        count(*) FILTER (WHERE kind = 'group')    AS active_groups,
        count(*) FILTER (WHERE kind = 'role')     AS active_roles,
        count(*) FILTER (WHERE kind = 'license')  AS active_licenses
    FROM active_access
    GROUP BY employee_id
)
SELECT
    e.id                                  AS employee_db_id,
    e.employee_id,
    e.first_name || ' ' || e.last_name    AS employee_name,
    e.department,
    e.termination_date,
    a.account_status,
    coalesce(c.active_groups, 0)          AS active_groups,
    coalesce(c.active_roles, 0)           AS active_roles,
    coalesce(c.active_licenses, 0)        AS active_licenses
FROM employees AS e
LEFT JOIN identity_accounts AS a ON a.employee_id = e.id
LEFT JOIN access_counts AS c ON c.employee_id = e.id
WHERE e.employment_status = 'terminated'
  AND (a.account_status = 'active' OR c.employee_id IS NOT NULL)
ORDER BY e.termination_date NULLS FIRST, e.id;
