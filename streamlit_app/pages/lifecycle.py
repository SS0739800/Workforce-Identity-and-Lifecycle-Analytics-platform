import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_app import api, ui

ui.header("Lifecycle")
start, end = ui.date_filter()

try:
    summary = api.analytics("workflow-summary", start, end)
    failures = api.analytics("workflow-failures", start, end)
    offboarding = api.analytics("offboarding", start, end)
except api.ApiError as error:
    ui.show_error(error)

rows = summary["by_type"]
completed = sum(row["completed"] for row in rows)
failed = sum(row["failed"] for row in rows)
disable = offboarding["time_to_disable"]
ui.metric_row([
    ("Workflows", sum(row["workflows"] for row in rows)),
    ("Success rate", ui.pct(100 * completed / (completed + failed) if completed + failed else None)),
    ("Service-desk re-runs", sum(row["service_desk_reruns"] for row in rows)),
    ("Pending", len(summary["pending"])),
    ("Median hours to disable", disable["median_hours_to_disable"]),
    ("Still enabled after termination", disable["still_enabled"]),
], help_text={"Median hours to disable": "From HR marking the employee terminated to the account being disabled."})

left, right = st.columns(2)
with left:
    st.markdown("**By workflow type**")
    ui.table(summary["by_type"], columns=["workflow_type", "workflows", "completed", "failed", "pending",
                                          "service_desk_reruns", "success_rate_pct"],
             rename={"workflow_type": "Type", "service_desk_reruns": "Re-runs", "success_rate_pct": "Success %"})
    ui.table(summary["durations"], rename={"workflow_type": "Type", "avg_seconds": "Avg s",
                                           "median_seconds": "Median s", "p90_seconds": "p90 s"})
with right:
    actions = pd.DataFrame(failures["by_action"]).dropna(subset=["failure_rate_pct"])
    if not actions.empty:
        figure = px.bar(actions.sort_values("failure_rate_pct"), x="failure_rate_pct", y="action_type",
                        orientation="h", hover_data=["failures", "attempts"], color_discrete_sequence=[ui.ACCENT])
        figure.update_xaxes(ticksuffix="%")
        ui.chart(figure, "Action failure rate", height=380)

monthly = pd.DataFrame(summary["monthly"])
if not monthly.empty:
    monthly["workflow"] = monthly["workflow_type"].map(ui.WORKFLOW_LABELS)
    figure = px.bar(monthly, x="month", y="workflows", color="workflow", barmode="stack")
    ui.chart(figure, "Workflows by month")

errors = pd.DataFrame(failures["by_error_type"])
if not errors.empty:
    grid = errors.pivot_table(index="action_type", columns="error_type", values="failures", fill_value=0)
    figure = px.imshow(grid, text_auto=True, aspect="auto", color_continuous_scale=[ui.SURFACE, ui.ACCENT])
    figure.update_coloraxes(showscale=False)
    ui.chart(figure, "Failed actions by error type", height=360)
st.caption("License removal fails more often than group removal because the simulation assumes a less reliable "
           "licensing API. The data shows that it happens, not why.")

st.subheader("Pending workflows")
ui.table(summary["pending"], columns=["workflow_run_id", "workflow_type", "employee_id", "employee_name",
                                      "termination_date", "requested_at"])

st.subheader("Workflow lookup")
workflow_id = st.number_input("Workflow run ID", min_value=1, step=1, value=None, placeholder="e.g. 362")
if workflow_id:
    try:
        run = api.workflow(int(workflow_id))
    except api.ApiError as error:
        st.warning(str(error))
    else:
        st.markdown(f"**#{run['id']} · {run['workflow_type']} · {run['status']}** · started by "
                    f"{run['initiated_by']} · requested {run['requested_at']}")
        ui.table(run["actions"], columns=["action_type", "target_name", "status", "error_type", "error_message",
                                          "started_at", "completed_at"])
