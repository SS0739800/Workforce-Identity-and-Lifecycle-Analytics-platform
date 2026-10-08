// fact_attribute_changes: one row per HR attribute change.
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "fact_attribute_changes"]}[Data],
    Typed = Table.TransformColumnTypes(View, {
        {"change_key", Int64.Type},
        {"employee_key", Int64.Type},
        {"date", type date},
        {"attribute_name", type text},
        {"source", type text},
        {"is_correction", type logical}
    })
in
    Typed
