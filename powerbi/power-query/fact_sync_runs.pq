// fact_sync_runs: one row per sync run. Relates to dim_date on date (no employee: a run covers everyone).
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_sync_runs"]}[Data],
    // Timestamps arrive as UTC date-time-zone values; the model stores plain date-times, labelled UTC.
    ToUtc = Table.TransformColumns(View, {{"started_at", DateTimeZone.RemoveZone, type datetime}}),
    Renamed = Table.RenameColumns(ToUtc, {{"started_at", "started_at_utc"}}),
    Typed = Table.TransformColumnTypes(Renamed, {
        {"sync_run_key", Int64.Type},
        {"run_id", type text},
        {"date", type date},
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
