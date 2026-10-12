"""Identity operations console (Streamlit).

Run from the project root, with the API running:
    streamlit run streamlit_app/app.py
"""

import sys
from pathlib import Path

import streamlit as st

# Streamlit runs this file as a script; make the project root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit_app.api import BASE_URL  # noqa: E402

st.set_page_config(page_title="Identity Operations", layout="wide")

pages = [
    st.Page("pages/overview.py", title="Overview", default=True),
    st.Page("pages/employees.py", title="Employees"),
    st.Page("pages/synchronization.py", title="Synchronization"),
    st.Page("pages/lifecycle.py", title="Lifecycle"),
    st.Page("pages/data_quality.py", title="Data Quality"),
    st.Page("pages/ai_insights.py", title="AI Insights"),
]

with st.sidebar:
    st.markdown("**Northstar Manufacturing**  \nIdentity operations · synthetic data")

st.navigation(pages).run()

with st.sidebar:
    st.divider()
    st.caption(f"API: {BASE_URL}")
