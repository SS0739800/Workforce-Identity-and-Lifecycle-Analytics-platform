-- Which departments generate the most HR changes?
-- Uses the employee's current department, so a transfer is counted under the new department.
SELECT
    coalesce(e.department, '(blank)')  AS department,
    count(*)                           AS changes,
    count(DISTINCT c.employee_id)      AS employees_changed
FROM attribute_change_logs AS c
JOIN employees AS e ON e.id = c.employee_id
WHERE c.changed_at >= :start_date
  AND c.changed_at < :end_date
GROUP BY e.department
ORDER BY changes DESC;
