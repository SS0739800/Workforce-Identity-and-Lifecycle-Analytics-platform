// fact_workflow_runs: one row per workflow run. date = the day it was requested.
// Relates to dim_date on date and dim_employee on employee_key.
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_workflow_runs"]}[Data],
    ToUtc = Table.TransformColumns(View, {
        {"requested_at", DateTimeZone.RemoveZone, type datetime},
        {"started_at", DateTimeZone.RemoveZone, type datetime},
        {"completed_at", DateTimeZone.RemoveZone, type datetime}
    }),
    Renamed = Table.RenameColumns(ToUtc, {
        {"requested_at", "requested_at_utc"},
        {"started_at", "started_at_utc"},
        {"completed_at", "completed_at_utc"}
    }),
    Typed = Table.TransformColumnTypes(Renamed, {
        {"workflow_key", Int64.Type},
        {"employee_key", Int64.Type},
        {"date", type date},
        {"workflow_type", type text},
        {"status", type text},
        {"initiated_by", type text},
        {"is_rerun", type logical},
        {"duration_seconds", type number},
        {"actions", Int64.Type},
        {"failed_actions", Int64.Type}
    })
in
    Typed
