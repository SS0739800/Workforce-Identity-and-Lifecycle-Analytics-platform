"""Identity operations console (Streamlit).

Run from the project root, with the API running:
    streamlit run streamlit_app/app.py
"""

import sys
from pathlib import Path

import streamlit as st

# Streamlit runs this file as a script; make the project root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAVICON = Path(__file__).parent / "assets" / "favicon.png"  # an identity record on a Fluent blue tile
st.set_page_config(page_title="Identity Operations", page_icon=str(FAVICON), layout="wide")

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
