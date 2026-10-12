// fact_workflow_runs: one row per workflow run. date = the day it was requested.
// Relates to dim_date on date and dim_employee on employee_key.
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_workflow_runs"]}[Data],
    // The view provides *_utc columns as plain UTC timestamps; the time-zone-aware
    // originals don't convert reliably in the connector, so they are dropped here.
    WithoutZonedTimes = Table.RemoveColumns(View, {"requested_at", "started_at", "completed_at"}),
    Typed = Table.TransformColumnTypes(WithoutZonedTimes, {
        {"workflow_key", Int64.Type},
        {"employee_key", Int64.Type},
        {"date", type date},
        {"workflow_type", type text},
        {"status", type text},
        {"initiated_by", type text},
        {"is_rerun", type logical},
        {"requested_at_utc", type datetime},
        {"started_at_utc", type datetime},
        {"completed_at_utc", type datetime},
        {"duration_seconds", type number},
        {"actions", Int64.Type},
        {"failed_actions", Int64.Type}
    })
in
    Typed
