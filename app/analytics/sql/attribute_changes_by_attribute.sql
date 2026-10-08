-- Which HR attributes change most often, and how many changes are data corrections?
SELECT
    attribute_name,
    count(*)                                              AS changes,
    count(*) FILTER (WHERE source = 'hr_system')          AS hr_changes,
    count(*) FILTER (WHERE source = 'data_correction')    AS corrections,
    count(DISTINCT employee_id)                           AS employees_affected
FROM attribute_change_logs
WHERE changed_at >= :start_date
  AND changed_at < :end_date
GROUP BY attribute_name
ORDER BY changes DESC;
