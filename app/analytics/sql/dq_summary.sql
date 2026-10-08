-- How many data-quality issues were found, and how quickly are they resolved?
SELECT
    count(*)                                                       AS total_issues,
    count(*) FILTER (WHERE status = 'open')                        AS open_issues,
    count(*) FILTER (WHERE status = 'resolved')                    AS resolved_issues,
    count(*) FILTER (WHERE status = 'open' AND severity = 'critical') AS open_critical_issues,
    count(DISTINCT employee_id) FILTER (WHERE status = 'open')     AS employees_with_open_issues,
    round(
        (avg(extract(epoch FROM resolved_at - detected_at)) FILTER (WHERE status = 'resolved') / 86400)::numeric,
        1
    )                                                              AS avg_days_to_resolve
FROM data_quality_issues
WHERE detected_at >= :start_date
  AND detected_at < :end_date;
