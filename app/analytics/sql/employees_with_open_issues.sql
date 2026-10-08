-- Which employees have unresolved data-quality issues? (current state)
WITH open_issues AS (
    SELECT
        employee_id,
        issue_type,
        severity,
        detected_at,
        CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END AS severity_rank
    FROM data_quality_issues
    WHERE status = 'open'
)
SELECT
    e.id                                                        AS employee_db_id,
    e.employee_id,
    e.first_name || ' ' || e.last_name                          AS employee_name,
    e.department,
    e.employment_status,
    count(*)                                                    AS open_issues,
    string_agg(o.issue_type, ', ' ORDER BY o.issue_type)        AS issue_types,
    (array_agg(o.severity ORDER BY o.severity_rank DESC))[1]    AS highest_severity,
    min(o.detected_at)                                          AS oldest_detected_at
FROM open_issues AS o
JOIN employees AS e ON e.id = o.employee_id
GROUP BY e.id
ORDER BY max(o.severity_rank) DESC, oldest_detected_at;
