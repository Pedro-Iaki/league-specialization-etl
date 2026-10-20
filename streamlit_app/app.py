from __future__ import annotations

from app_core.i18n import language_selector, st, t
from app_core.story import STORY_PAGES

st.set_page_config(page_title="players-as-customers-pipeline", page_icon="◈", layout="wide")
st.session_state["_dashboard_app_shell"] = True
language_selector()

pages = {
    t("The story"): [
        st.Page(path, title=f"{index} · {t(title)}", default=index == 1)
        for index, (path, title) in enumerate(STORY_PAGES, 1)
    ],
    t("Explore the data"): [
        st.Page("pages/1_Overall_Analysis.py", title="Population"),
        st.Page("overview.py", title="Specialization and rank"),
        st.Page("pages/3_Notable_Champions.py", title="Cross-champion"),
        st.Page("pages/2_Champion_Explorer.py", title="Champion Explorer"),
        st.Page("pages/4_Population_Estimates.py", title="Population Estimates"),
        st.Page("business.py", title="Business sample"),
    ],
}

st.navigation(pages, expanded=True).run()
