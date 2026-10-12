// fact_sync_runs: one row per sync run. Relates to dim_date on date (no employee: a run covers everyone).
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_sync_runs"]}[Data],
    // The view provides started_at_utc as a plain UTC timestamp; the time-zone-aware
    // original doesn't convert reliably in the connector, so it is dropped here.
    WithoutZonedTimes = Table.RemoveColumns(View, {"started_at"}),
    Typed = Table.TransformColumnTypes(WithoutZonedTimes, {
        {"sync_run_key", Int64.Type},
        {"run_id", type text},
        {"date", type date},
        {"started_at_utc", type datetime},
        {"status", type text},
        {"triggered_by", type text},
        {"total_records", Int64.Type},
        {"successful_records", Int64.Type},
        {"failed_records", Int64.Type},
        {"skipped_records", Int64.Type},
        {"duration_seconds", type number},
        {"error_message", type text}
    })
in
    Typed
