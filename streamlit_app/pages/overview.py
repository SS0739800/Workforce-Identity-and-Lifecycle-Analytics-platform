import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from streamlit_app import api, ui

ui.header("Identity Operations Overview", "What is happening across identity operations?")
start, end = ui.date_filter()

try:
    sync = api.analytics("sync-summary", start, end)
    trends = api.analytics("sync-trends", start, end)
    workflows = api.analytics("workflow-summary", start, end)
    quality = api.analytics("data-quality", start, end)
    offboarding = api.analytics("offboarding", start, end)
    active = api.employees(status="active", limit=1)
except api.ApiError as error:
    ui.show_error(error)

completed = sum(row["completed"] for row in workflows["by_type"])
failed = sum(row["failed"] for row in workflows["by_type"])
failure_rate = 100 * failed / (completed + failed) if completed + failed else None

ui.metric_row([
    ("Active employees", f"{active['total']:,}"),
    ("Sync success rate", ui.pct(sync["totals"]["record_success_rate_pct"])),
    ("Workflow failure rate", ui.pct(failure_rate)),
    ("Open data-quality issues", quality["totals"]["open_issues"]),
    ("Leavers with access remaining", len(offboarding["access_remaining"])),
    ("Pending workflows", len(workflows["pending"])),
], help_text={
    "Sync success rate": "Records updated ÷ records the sync tried to update. Unchanged records are excluded.",
    "Workflow failure rate": "Failed ÷ (completed + failed). Pending workflows are excluded.",
    "Leavers with access remaining": "Terminated employees who still have an enabled account or any access (current state).",
})

left, right = st.columns(2)
with left:
    monthly = pd.DataFrame(workflows["monthly"])
    if monthly.empty:
        st.info("No workflows in this period.")
    else:
        monthly["workflow"] = monthly["workflow_type"].map(ui.WORKFLOW_LABELS)
        figure = px.line(monthly, x="month", y="workflows", color="workflow", markers=True)
        ui.chart(figure, "Lifecycle workflows by month")
with right:
    months = pd.DataFrame(trends["months"])
    if months.empty:
        st.info("No sync runs in this period.")
    else:
        failed_workflows = monthly.groupby("month")["failed"].sum() if not monthly.empty else pd.Series(dtype=int)
        figure = go.Figure([
            go.Bar(x=months["month"], y=months["records_failed"], name="Sync records failed", marker_color=ui.ACCENT),
            go.Bar(x=failed_workflows.index, y=failed_workflows.values, name="Workflows failed", marker_color=ui.NEUTRAL),
        ])
        ui.chart(figure, "Failures by month")

st.subheader("Leavers with access remaining")
st.caption("Highest-risk item on this page: accounts or access that offboarding left behind. "
           "Select a row to open the employee.")
leavers = offboarding["access_remaining"]
selection = ui.table(
    leavers,
    columns=["employee_db_id", "employee_id", "employee_name", "department", "termination_date", "account_status",
             "active_groups", "active_roles", "active_licenses"],
    rename={"employee_db_id": "ID", "employee_id": "HR ID", "employee_name": "Name", "termination_date": "Terminated",
            "account_status": "Account", "active_groups": "Groups", "active_roles": "Roles",
            "active_licenses": "Licenses"},
    on_select="rerun", selection_mode="single-row", key="leavers",
)
if selection and selection.selection.rows:
    st.session_state["employee_id"] = leavers[selection.selection.rows[0]]["employee_db_id"]
    st.switch_page("pages/employees.py")
