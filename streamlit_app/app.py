"""Default portfolio dashboard: the approved seven-chapter audience story."""

import streamlit as st
from app_core.story_app import render_story
from app_core.story_localization import host_text

st.set_page_config(page_title=host_text("chrome.document_title"), page_icon="◈", layout="wide")
# Explicit navigation disables automatic discovery of the legacy pages directory.
st.navigation([st.Page(render_story, title=host_text("host.page"), default=True)], position="hidden").run()
