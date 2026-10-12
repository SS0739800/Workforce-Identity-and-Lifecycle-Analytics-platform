import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from streamlit_app import api, ui

ui.header("Synchronization")
start, end = ui.date_filter()

try:
    summary = api.analytics("sync-summary", start, end)
    trends = api.analytics("sync-trends", start, end)
    runs = api.get("/api/sync/runs", limit=200)
except api.ApiError as error:
    ui.show_error(error)

totals = summary["totals"]
ui.metric_row([
    ("Sync runs", totals["total_runs"]),
    ("Failed runs", totals["failed_runs"]),
    ("Records attempted", totals["records_updated"] + totals["records_failed"]),
    ("Record success rate", ui.pct(totals["record_success_rate_pct"])),
    ("Records evaluated", f"{totals['records_evaluated']:,}"),
], help_text={
    "Failed runs": "Runs that failed as a whole (missing HR export, missing column, directory outage).",
    "Records attempted": "Changed records and new hires the sync tried to update.",
    "Records evaluated": "Every record in the HR export on every run, including unchanged ones.",
})

months = pd.DataFrame(trends["months"])
if months.empty:
    st.info("No sync runs in this period.")
else:
    figure = go.Figure([
        go.Bar(x=months["month"], y=months["records_updated"], name="Updated", marker_color=ui.NEUTRAL),
        go.Bar(x=months["month"], y=months["records_failed"], name="Failed", marker_color=ui.ACCENT),
        go.Scatter(x=months["month"], y=months["record_failure_rate_pct"], name="Failure rate %",
                   yaxis="y2", mode="lines+markers", line={"color": ui.MUTED}),
    ])
    figure.update_layout(barmode="stack", yaxis2={"overlaying": "y", "side": "right", "showgrid": False,
                                                  "rangemode": "tozero", "ticksuffix": "%"})
    ui.chart(figure, "Sync volume and failures by month")

left, right = st.columns(2)
with left:
    errors = pd.DataFrame(summary["failures_by_error_type"])
    if errors.empty:
        st.info("No failed records in this period.")
    else:
        figure = px.bar(errors.sort_values("failures"), x="failures", y="error_type", orientation="h",
                        color_discrete_sequence=[ui.ACCENT])
        ui.chart(figure, "Failed records by error type")
with right:
    st.markdown("**Failures by department**")
    ui.table(
        summary["failures_by_department"],
        rename={"department": "Department", "sync_attempts": "Attempts", "failures": "Failures",
                "failure_rate_pct": "Failure rate %"},
        column_config={"Failure rate %": st.column_config.ProgressColumn(
            "Failure rate %", format="%.1f%%", min_value=0, max_value=100)},
    )

st.subheader("Failed runs")
failed_runs = [run for run in runs if run["status"] == "failed"]
ui.table(failed_runs, columns=["started_at", "run_id", "triggered_by", "error_message"])

st.subheader("Run sync")
st.caption("Processes HR changes since the last sync and starts any onboarding, offboarding, leave or "
           "return workflows they need.")
confirm = st.checkbox("Confirm: this changes data")
if st.button("Run sync", type="primary", disabled=not confirm):
    with st.spinner("Running sync..."):
        try:
            result = api.post("/api/sync/runs")
            run = result["run"]
            st.success(f"{run['run_id']}: {run['status']} · {run['successful_records']} updated · "
                       f"{run['failed_records']} failed · {len(result['workflows_started'])} workflows started")
            ui.table(result["workflows_started"])
        except api.ApiError as error:
            st.warning(str(error))
