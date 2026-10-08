// dim_date: one row per calendar day. Mark as the model's date table (column: date).
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "dim_date"]}[Data],
    Typed = Table.TransformColumnTypes(View, {
        {"date", type date},
        {"year", Int64.Type},
        {"quarter", Int64.Type},
        {"quarter_label", type text},
        {"quarter_start", type date},
        {"month_number", Int64.Type},
        {"month_start", type date},
        {"month_label", type text},
        {"day_of_week", Int64.Type},
        {"is_weekday", type logical}
    })
in
    Typed
