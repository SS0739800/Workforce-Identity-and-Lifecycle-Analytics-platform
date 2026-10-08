-- Which employees had the most HR changes?
SELECT
    e.id,
    e.employee_id,
    e.first_name || ' ' || e.last_name  AS employee_name,
    e.department,
    count(*)                            AS changes,
    count(DISTINCT c.attribute_name)    AS attributes_changed
FROM attribute_change_logs AS c
JOIN employees AS e ON e.id = c.employee_id
WHERE c.changed_at >= :start_date
  AND c.changed_at < :end_date
GROUP BY e.id
ORDER BY changes DESC, e.id
LIMIT :limit;
