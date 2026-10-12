"""AI explanations of computed data. The facts behind every answer are shown with it."""

from datetime import date

import pandas as pd
import streamlit as st

from streamlit_app import api, ui

ui.header("AI Insights", "Plain-language explanations of the numbers, grounded in the data")
st.caption("Every answer starts from an approved SQL query. The model explains those numbers; it never writes "
           "SQL or produces figures of its own. Names and emails are never sent to the model.")

EXAMPLES = [
    "Which departments had the most synchronization failures this quarter?",
    "What were the most common offboarding failures last month?",
    "Why do sync records fail?",
    "Which licenses fail to be removed at offboarding?",
    "How quickly are accounts disabled after termination?",
]


def show_result(result: dict):
    ui.ai_status(result)
    if result.get("explanation"):
        st.markdown(result["explanation"])
    elif result.get("message"):
        st.write(result["message"])
    with st.expander("Facts sent to the model"):
        facts = result["facts"]
        rows = facts.get("rows")
        if rows:
            st.caption(f"Query `{facts['query']}` · {facts['period']['description']} · {facts['row_count']} rows")
            ui.table(rows)
        else:
            st.json(facts, expanded=False)


def run(label: str, call):
    with st.spinner(label):
        try:
            st.session_state["ai_result"] = call()
        except api.ApiError as error:
            st.session_state["ai_result"] = None
            st.warning(str(error))


ask, failures, summary, quality, incident, log = st.tabs(
    ["Ask a question", "Failure explanation", "Monthly summary", "Data quality", "Incident report", "Request log"])

with ask:
    question = st.text_input("Question", placeholder=EXAMPLES[0], key="question")
    chosen = st.pills("Examples", EXAMPLES, key="example")
    # The button stays enabled: a typed question is only committed when the page re-runs,
    # so a disabled button would ignore the first click after typing.
    if st.button("Ask", type="primary"):
        if question or chosen:
            run("Answering...", lambda: api.post("/api/ai/ask", {"question": question or chosen}))
        else:
            st.warning("Type a question or pick an example.")

with failures:
    failure_question = st.text_input(
        "Question", value="Why are license removal failures higher than group removal failures?")
    if st.button("Explain", type="primary"):
        run("Explaining...", lambda: api.post("/api/ai/failure-explanation", {"question": failure_question}))

with summary:
    month = st.date_input("Month", value=date(2026, 9, 1), format="YYYY-MM-DD")
    if st.button("Write summary", type="primary"):
        run("Writing summary...", lambda: api.post("/api/ai/executive-summary", month=month.strftime("%Y-%m")))

with quality:
    if st.button("Explain data quality", type="primary"):
        run("Explaining...", lambda: api.post("/api/ai/data-quality-explanation"))

with incident:
    workflow_id = st.number_input("Failed workflow run ID", min_value=1, step=1, value=None, placeholder="e.g. 362")
    if st.button("Write incident report", type="primary"):
        if workflow_id:
            run("Writing incident report...", lambda: api.post(f"/api/ai/incident-report/{int(workflow_id)}"))
        else:
            st.warning("Enter the ID of a failed workflow.")

with log:
    st.caption("Every AI request is logged with a short summary. Full prompts are never stored.")
    try:
        ui.table(api.get("/api/ai/runs", limit=50),
                 columns=["id", "requested_at", "insight_type", "status", "model", "input_summary", "error_message"])
    except api.ApiError as error:
        st.warning(str(error))

result = st.session_state.get("ai_result")
if result:
    st.divider()
    st.subheader("Result")
    show_result(result)
