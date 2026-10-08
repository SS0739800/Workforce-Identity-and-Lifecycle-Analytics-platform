// dim_workflow_type: the four lifecycle workflows. Relates to fact_workflow_runs and
// fact_workflow_actions on workflow_type, so one slicer filters both. Sort workflow_label by sort_order.
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "dim_workflow_type"]}[Data],
    Typed = Table.TransformColumnTypes(View, {
        {"workflow_type", type text},
        {"workflow_label", type text},
        {"sort_order", Int64.Type}
    })
in
    Typed
