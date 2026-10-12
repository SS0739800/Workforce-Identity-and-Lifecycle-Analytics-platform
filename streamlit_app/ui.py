"""Shared page pieces: headers, filters, metric rows, tables and status labels."""

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from streamlit_app.api import ApiError

# One neutral colour for normal values, one accent for failures, used the same way everywhere.
NEUTRAL = "#3A6EA5"
ACCENT = "#D9822B"
MUTED = "#A19F9D"
SERIES = [NEUTRAL, "#7FA7CF", "#5B8C5A", "#8E6C8A", MUTED]
# Plotly Express picks its own colours unless told otherwise; red would read as "failure".
px.defaults.color_discrete_sequence = SERIES

WORKFLOW_LABELS = {"onboarding": "Onboarding", "offboarding": "Offboarding", "leave": "Leave",
                   "return_from_leave": "Return from leave"}

# The simulated year. Used as the default date range.
DATA_START = date(2025, 10, 1)
DATA_END = date(2026, 9, 30)


def header(title: str, question: str):
    st.title(title)
    st.caption(question)


def date_filter() -> tuple[date | None, date | None]:
    """Sidebar date range, shared by every page through session state."""
    with st.sidebar:
        st.subheader("Period")
        everything = st.toggle("All data", value=st.session_state.get("all_data", True), key="all_data")
        if everything:
            return None, None
        chosen = st.date_input(
            "Date range", value=st.session_state.get("date_range", (DATA_START, DATA_END)), key="date_range",
            format="YYYY-MM-DD",
        )
    if isinstance(chosen, (list, tuple)) and len(chosen) == 2:
        return chosen[0], chosen[1]
    return None, None  # only one date picked so far


def show_error(error: ApiError):
    st.error(str(error))
    st.stop()


def metric_row(items: list[tuple[str, object]], help_text: dict | None = None):
    columns = st.columns(len(items))
    for column, (label, value) in zip(columns, items):
        column.metric(label, "-" if value is None else value, help=(help_text or {}).get(label))


def when(value: str | None) -> str:
    """'2026-09-17T02:02:10Z' -> '2026-09-17 02:02 UTC'."""
    if not value:
        return "-"
    return pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%d %H:%M UTC")


def pct(value: float | None) -> str | None:
    return None if value is None else f"{value:.1f}%"


def table(rows: list[dict], columns: list[str] | None = None, rename: dict | None = None, **kwargs):
    if not rows:
        st.info("No rows for this selection.")
        return None
    frame = pd.DataFrame(rows)
    if columns:
        frame = frame[[c for c in columns if c in frame.columns]]
    for column in frame.columns:
        if column.endswith("_at") or column == "timestamp":
            frame[column] = pd.to_datetime(frame[column], utc=True).dt.strftime("%Y-%m-%d %H:%M")
    # Readable headers by default ("open_issues" -> "Open issues"); explicit names win.
    headers = {c: c.replace("_", " ").capitalize() for c in frame.columns}
    headers.update(rename or {})
    frame = frame.rename(columns=headers)
    return st.dataframe(frame, hide_index=True, width="stretch", **kwargs)


def style_figure(figure: go.Figure, title: str, height: int = 340) -> go.Figure:
    figure.update_layout(
        title={"text": title, "font": {"size": 15}},
        height=height,
        margin={"l": 10, "r": 10, "t": 45, "b": 10},
        legend={"orientation": "h", "y": -0.18, "title": None},
        plot_bgcolor="white",
        paper_bgcolor="white",
        colorway=SERIES,
        font={"family": "Segoe UI, sans-serif", "size": 12},
    )
    figure.update_xaxes(showgrid=False, title=None)
    figure.update_yaxes(gridcolor="#EDEBE9", title=None, rangemode="tozero")
    return figure


def chart(figure: go.Figure, title: str, height: int = 340):
    st.plotly_chart(style_figure(figure, title, height), width="stretch", config={"displayModeBar": False})


STATUS_LABELS = {
    "ok": ("success", "Explanation generated from the data"),
    "needs_review": ("warning", "Check before using: some numbers in the explanation are not in the data"),
    "unavailable": ("info", "AI not configured or unreachable: showing the computed data"),
    "rate_limited": ("warning", "AI rate limit reached: showing the computed data"),
    "timeout": ("warning", "AI timed out: showing the computed data"),
    "invalid_response": ("warning", "AI returned an unusable answer: showing the computed data"),
    "error": ("warning", "AI error: showing the computed data"),
    "unmatched": ("info", "This question doesn't match an approved query"),
    "no_data": ("info", "The query returned no rows for this period"),
}


def ai_status(result: dict):
    kind, text = STATUS_LABELS.get(result["ai_status"], ("info", result["ai_status"]))
    model = f" · model: {result['model']}" if result.get("model") else ""
    getattr(st, kind)(f"{text}{model}")
    if result.get("ungrounded_numbers"):
        st.caption("Numbers not found in the data: " + ", ".join(result["ungrounded_numbers"]))
