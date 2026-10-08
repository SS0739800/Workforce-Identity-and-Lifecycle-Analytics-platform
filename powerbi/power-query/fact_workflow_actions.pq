// fact_workflow_actions: one row per workflow step. Carries workflow_type and employee_key
// itself, so it relates directly to dim_date (date) and dim_employee (employee_key).
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_workflow_actions"]}[Data],
    Typed = Table.TransformColumnTypes(View, {
        {"action_key", Int64.Type},
        {"workflow_key", Int64.Type},
        {"employee_key", Int64.Type},
        {"date", type date},
        {"workflow_type", type text},
        {"action_type", type text},
        {"target_name", type text},
        {"status", type text},
        {"is_attempt", type logical},
        {"error_type", type text},
        {"duration_seconds", type number}
    })
in
    Typed
