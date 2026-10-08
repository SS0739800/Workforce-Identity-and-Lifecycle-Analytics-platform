-- Which departments have the most data-quality issues?
-- Uses the employee's current department; '(blank)' means the department field itself is empty.
SELECT
    coalesce(e.department, '(blank)')          AS department,
    count(*)                                   AS issues,
    count(*) FILTER (WHERE d.status = 'open')  AS open_issues,
    count(DISTINCT d.employee_id)              AS employees_affected
FROM data_quality_issues AS d
JOIN employees AS e ON e.id = d.employee_id
WHERE d.detected_at >= :start_date
  AND d.detected_at < :end_date
GROUP BY e.department
ORDER BY issues DESC;
