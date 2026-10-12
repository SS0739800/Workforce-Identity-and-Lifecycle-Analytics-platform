import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from streamlit_app import api, ui

ui.header("Data Quality", "Where does the HR data have problems, and do they affect operations?")
start, end = ui.date_filter()

try:
    quality = api.analytics("data-quality", start, end)
except api.ApiError as error:
    ui.show_error(error)

totals = quality["totals"]
ui.metric_row([
    ("Issues found", totals["total_issues"]),
    ("Open", totals["open_issues"]),
    ("Resolved", totals["resolved_issues"]),
    ("Open critical", totals["open_critical_issues"]),
    ("Employees with open issues", totals["employees_with_open_issues"]),
    ("Avg days to resolve", totals["avg_days_to_resolve"]),
], help_text={"Open": "Issues detected in the selected period that are still open."})

left, right = st.columns(2)
with left:
    monthly = pd.DataFrame(quality["monthly"])
    if not monthly.empty:
        figure = go.Figure([
            go.Bar(x=monthly["month"], y=monthly["detected"], name="Found", marker_color=ui.ACCENT),
            go.Bar(x=monthly["month"], y=monthly["resolved"], name="Fixed", marker_color=ui.NEUTRAL),
        ])
        ui.chart(figure, "Found vs fixed by month")
with right:
    by_type = pd.DataFrame(quality["by_type"])
    if not by_type.empty:
        long = by_type.melt(id_vars=["issue_type"], value_vars=["open_issues", "resolved_issues"],
                            var_name="status", value_name="count")
        long["status"] = long["status"].map({"open_issues": "open", "resolved_issues": "resolved"})
        long = long.groupby(["issue_type", "status"], as_index=False)["count"].sum()
        figure = px.bar(long, x="count", y="issue_type", color="status", orientation="h",
                        color_discrete_map={"open": ui.ACCENT, "resolved": ui.MUTED})
        figure.update_yaxes(categoryorder="total ascending")
        ui.chart(figure, "Issues by type")

left, right = st.columns(2)
with left:
    st.markdown("**By field and severity**")
    ui.table(quality["by_type"], columns=["issue_type", "field_name", "severity", "issues", "open_issues",
                                          "avg_days_to_resolve"])
with right:
    st.markdown("**By department**")
    ui.table(quality["by_department"])

st.subheader("Do data-quality issues affect the sync?")
impact = pd.DataFrame(quality["sync_impact"])
if not impact.empty:
    impact["records"] = impact["had_open_issue"].map({True: "Open issue at the time", False: "No open issue"})
    figure = px.bar(impact, x="records", y="failure_rate_pct", text="failure_rate_pct",
                    color="records", color_discrete_map={"Open issue at the time": ui.ACCENT, "No open issue": ui.NEUTRAL})
    figure.update_traces(texttemplate="%{text:.1f}%", showlegend=False)
    figure.update_yaxes(ticksuffix="%")
    ui.chart(figure, "Sync failure rate", height=300)
st.caption("Records with an open data-quality issue fail to sync far more often. In this synthetic dataset that "
           "link is built in (the sync validates the same rules the scan checks), so this shows an association, "
           "not a measured cause.")

st.subheader("Employees with open issues")
issues = quality["employees_with_open_issues"]
selection = ui.table(
    issues,
    columns=["employee_db_id", "employee_id", "employee_name", "department", "employment_status", "open_issues",
             "issue_types", "highest_severity", "oldest_detected_at"],
    rename={"employee_db_id": "ID", "employee_id": "HR ID", "employee_name": "Name"},
    on_select="rerun", selection_mode="single-row", key="open_issue_employees",
)
if selection and selection.selection.rows:
    st.session_state["employee_id"] = issues[selection.selection.rows[0]]["employee_db_id"]
    st.switch_page("pages/employees.py")

st.subheader("Run the data-quality scan")
st.caption("Re-checks every record: opens new issues and resolves fixed ones. This changes data.")
confirm = st.checkbox("I want to run the scan")
if st.button("Run scan", type="primary", disabled=not confirm):
    try:
        result = api.post("/api/data-quality/scans")
        st.success(f"Scanned {result['employees_scanned']:,} employees: {result['issues_opened']} opened, "
                   f"{result['issues_resolved']} resolved, {result['open_issues']} open now.")
    except api.ApiError as error:
        st.warning(str(error))
