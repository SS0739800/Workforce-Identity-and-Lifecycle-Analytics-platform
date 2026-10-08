-- Why do sync records fail?
SELECT
    error_type,
    count(*)                                            AS failures,
    -- share of all failed records in the period
    round(100.0 * count(*) / sum(count(*)) OVER (), 1)  AS share_pct
FROM sync_record_results
WHERE status = 'failed'
  AND started_at >= :start_date
  AND started_at < :end_date
GROUP BY error_type
ORDER BY failures DESC;
