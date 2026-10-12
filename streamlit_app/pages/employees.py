"""Employee investigation: everything known about one identity, on one screen."""

import pandas as pd
import streamlit as st

from streamlit_app import api, ui

ui.header("Employees")

# --- find an employee ----------------------------------------------------------------------------
search_column, status_column = st.columns([3, 1])
search = search_column.text_input("Search", placeholder="HR employee ID (EMP00042), name or email")
status = status_column.selectbox("Status", ["Any", "active", "terminated"])

try:
    results = api.employees(search=search, status=None if status == "Any" else status, limit=50)
except api.ApiError as error:
    ui.show_error(error)

st.caption(f"{results['total']:,} matching employees" + (" (showing the first 50)" if results["total"] > 50 else ""))
selection = ui.table(
    results["items"],
    columns=["id", "employee_id", "first_name", "last_name", "department", "job_title", "location",
             "employment_status", "leave_status"],
    rename={"id": "ID", "employee_id": "HR ID", "first_name": "First name", "last_name": "Last name",
            "department": "Department", "job_title": "Title", "location": "Location",
            "employment_status": "Status", "leave_status": "Leave"},
    on_select="rerun", selection_mode="single-row", key="employee_results", height=240,
)
if selection and selection.selection.rows:
    st.session_state["employee_id"] = results["items"][selection.selection.rows[0]]["id"]

# Deep link: /employees?employee=552 opens that employee directly.
if "employee" in st.query_params and st.query_params["employee"].isdigit():
    st.session_state["employee_id"] = int(st.query_params["employee"])

employee_id = st.session_state.get("employee_id")
if employee_id is None:
    st.info("Select an employee to see their details.")
    st.stop()

# --- the employee ----------------------------------------------------------------------------------
try:
    person = api.employee(employee_id)
    workflows = api.employee_section(employee_id, "workflows")
    changes = api.employee_section(employee_id, "changes")
    activity = api.employee_section(employee_id, "activity")
except api.ApiError as error:
    ui.show_error(error)

st.divider()
st.header(f"{person['first_name']} {person['last_name']}")
st.caption(" · ".join(str(part) for part in [
    person["employee_id"] or "no HR ID", person["job_title"] or "no title", person["department"] or "no department",
    person["location"] or "no location", person["employment_type"],
]))

account = person["identity_account"]
open_issues = [issue for issue in person["data_quality_issues"] if issue["status"] == "open"]
failed_workflows = [run for run in workflows if run["status"] == "failed"]

ui.metric_row([
    ("Employment", person["employment_status"] + (" · on leave" if person["leave_status"] == "on_leave" else "")),
    ("Identity account", account["account_status"] if account else "none"),
    ("Active groups", sum(g["status"] == "active" for g in person["groups"])),
    ("Active licenses", sum(lic["status"] == "active" for lic in person["licenses"])),
    ("Open DQ issues", len(open_issues)),
    ("Failed workflows", len(failed_workflows)),
])

# Flag the situations an IAM analyst would act on first.
if person["employment_status"] == "terminated" and account and account["account_status"] == "active":
    st.error("Terminated, but the identity account is still enabled.")
elif person["employment_status"] == "terminated" and any(
        item["status"] == "active" for item in person["groups"] + person["roles"] + person["licenses"]):
    st.warning("Terminated, but some access is still assigned.")
if person["employment_status"] == "active" and not account:
    st.warning("Active employee without an identity account.")

profile, access, workflow_tab, change_tab, quality_tab, activity_tab = st.tabs(
    ["Profile", "Access", f"Workflows ({len(workflows)})", f"Changes ({len(changes)})",
     f"Data quality ({len(person['data_quality_issues'])})", "Activity"])

with profile:
    left, right = st.columns(2)
    manager = person["manager"]
    left.markdown(
        f"**Hire date:** {person['hire_date']}  \n"
        f"**Termination date:** {person['termination_date'] or '-'}  \n"
        f"**Manager:** {manager['name'] + ' (' + (manager['employee_id'] or 'no HR ID') + ')' if manager else 'none'}  \n"
        f"**Email:** {person['email'] or '-'}"
    )
    if account:
        right.markdown(
            f"**Username:** {account['username']}  \n"
            f"**Account status:** {account['account_status']}  \n"
            f"**Created:** {ui.when(account['account_created_at'])}  \n"
            f"**Disabled:** {ui.when(account['account_disabled_at'])}  \n"
            f"**Last sync:** {ui.when(account['last_sync_at'])}"
        )
    else:
        right.markdown("**No identity account.**")

with access:
    for title, items in (("Groups", person["groups"]), ("Roles", person["roles"]), ("Licenses", person["licenses"])):
        st.markdown(f"**{title}**")
        ui.table(items, columns=["name", "status", "assigned_at", "removed_at"])

with workflow_tab:
    if not workflows:
        st.info("No workflows for this employee.")
    for run in workflows:
        failed_actions = [a for a in run["actions"] if a["status"] == "failed"]
        label = (f"#{run['id']} · {run['workflow_type']} · {run['status']} · {run['initiated_by']} · "
                 f"requested {ui.when(run['requested_at'])}")
        with st.expander(label, expanded=bool(failed_actions)):
            ui.table(run["actions"], columns=["action_type", "target_name", "status", "error_type",
                                              "error_message", "started_at", "completed_at"])
            if run["status"] == "failed":
                rerun_column, report_column = st.columns(2)
                confirm = rerun_column.checkbox("Confirm: this changes data", key=f"confirm_{run['id']}")
                if rerun_column.button("Re-run failed steps", key=f"rerun_{run['id']}", disabled=not confirm):
                    try:
                        rerun = api.post(f"/api/workflows/{run['id']}/rerun")
                        st.success(f"Re-run #{rerun['id']} finished: {rerun['status']}")
                    except api.ApiError as error:
                        st.warning(str(error))
                if report_column.button("Incident report (AI)", key=f"report_{run['id']}"):
                    with st.spinner("Writing incident report..."):
                        try:
                            report = api.post(f"/api/ai/incident-report/{run['id']}")
                            ui.ai_status(report)
                            st.markdown(report["explanation"] or report["message"])
                        except api.ApiError as error:
                            st.warning(str(error))

with change_tab:
    ui.table(changes, columns=["changed_at", "attribute_name", "old_value", "new_value", "source"])

with quality_tab:
    ui.table(person["data_quality_issues"], columns=["issue_type", "field_name", "severity", "status",
                                                     "description", "detected_at", "resolved_at"])

with activity_tab:
    st.caption("Identity audit events, failed sync attempts and data-quality findings, newest first.")
    frame = pd.DataFrame(activity)
    if not frame.empty:
        category = st.multiselect("Show", sorted(frame["category"].unique()), default=sorted(frame["category"].unique()))
        frame = frame[frame["category"].isin(category)]
    ui.table(frame.to_dict("records"), columns=["timestamp", "category", "event_type", "description", "source"])
