// dim_employee: current HR state per employee (no email). Key: employee_key.
let
    Source = PostgreSQL.Database(DatabaseServer, DatabaseName),
    View = Source{[Schema = "reporting", Item = "dim_employee"]}[Data],
    Typed = Table.TransformColumnTypes(View, {
        {"employee_key", Int64.Type},
        {"hr_employee_id", type text},
        {"employee_name", type text},
        {"department", type text},
        {"job_title", type text},
        {"location", type text},
        {"employment_type", type text},
        {"employment_status", type text},
        {"leave_status", type text},
        {"hire_date", type date},
        {"termination_date", type date},
        {"manager_name", type text},
        {"account_status", type text},
        {"has_access_after_termination", type logical},
        {"open_dq_issues", Int64.Type}
    }),
    // A blank HR employee ID is a data-quality finding; show it explicitly in tables and slicers.
    LabelledIds = Table.ReplaceValue(Typed, null, "(missing)", Replacer.ReplaceValue, {"hr_employee_id"})
in
    LabelledIds
