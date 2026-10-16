from __future__ import annotations

from app_core.i18n import language_selector, st

st.set_page_config(page_title="League Specialization · player profiles and business sample", page_icon="◈", layout="wide")
st.session_state["_dashboard_app_shell"] = True
language_selector()

pages = [
    st.Page("business.py", title="Business Sample", default=True),
    st.Page("overview.py", title="Overview"),
    st.Page("pages/1_Overall_Analysis.py", title="Population Analysis"),
    st.Page("pages/4_Population_Estimates.py", title="Population Estimates"),
    st.Page("pages/3_Notable_Champions.py", title="Cross Champion View"),
    st.Page("pages/2_Champion_Explorer.py", title="Champion Explorer"),
]

st.navigation(pages).run()
