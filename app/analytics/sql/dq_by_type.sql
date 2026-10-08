-- Which data-quality problems occur, on which field, and how serious are they?
SELECT
    issue_type,
    field_name,
    severity,
    count(*)                                      AS issues,
    count(*) FILTER (WHERE status = 'open')       AS open_issues,
    count(*) FILTER (WHERE status = 'resolved')   AS resolved_issues,
    round(
        (avg(extract(epoch FROM resolved_at - detected_at)) FILTER (WHERE status = 'resolved') / 86400)::numeric,
        1
    )                                             AS avg_days_to_resolve
FROM data_quality_issues
WHERE detected_at >= :start_date
  AND detected_at < :end_date
GROUP BY issue_type, field_name, severity
ORDER BY issues DESC, issue_type;
