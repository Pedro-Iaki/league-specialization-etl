from __future__ import annotations

import streamlit as st

pages = [
    st.Page("overview.py", title="Overview", default=True),
    st.Page("pages/1_Overall_Analysis.py", title="Population Analysis"),
    st.Page("pages/3_Notable_Champions.py", title="Cross Champion View"),
    st.Page("pages/2_Champion_Explorer.py", title="Champion Explorer"),
]

st.navigation(pages).run()
