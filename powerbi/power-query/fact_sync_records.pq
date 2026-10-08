// fact_sync_records: one row per record the sync tried to update (success or failure).
// Relates to dim_date on date and dim_employee on employee_key.
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_sync_records"]}[Data],
    Typed = Table.TransformColumnTypes(View, {
        {"sync_record_key", Int64.Type},
        {"sync_run_key", Int64.Type},
        {"employee_key", Int64.Type},
        {"date", type date},
        {"status", type text},
        {"error_type", type text},
        {"duration_seconds", type number},
        {"had_open_dq_issue", type logical}
    })
in
    Typed
