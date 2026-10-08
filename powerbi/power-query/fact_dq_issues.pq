// fact_dq_issues: one row per data-quality issue.
// detected_date -> dim_date is the active relationship; resolved_date -> dim_date is inactive
// and used only by the "Issues Resolved (by resolved date)" measure.
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_dq_issues"]}[Data],
    Typed = Table.TransformColumnTypes(View, {
        {"issue_key", Int64.Type},
        {"employee_key", Int64.Type},
        {"detected_date", type date},
        {"resolved_date", type date},
        {"issue_type", type text},
        {"field_name", type text},
        {"severity", type text},
        {"status", type text},
        {"days_to_resolve", type number}
    })
in
    Typed
