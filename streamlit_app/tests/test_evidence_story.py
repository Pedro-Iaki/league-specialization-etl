"""Engineering chapter keeps coverage truthful and evidence inspectable."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from app_core.data import DashboardDataError
from app_core.i18n import LANGUAGE_KEY, TERMINOLOGY_KEY
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'


@pytest.mark.parametrize('language,terms', [('EN', 'Plain'), ('PT', 'League')])
def test_engineering_inventory_and_coverage_use_the_matching_full_serving_scope(language, terms):
    app = AppTest.from_file(str(APP), default_timeout=45)
    app.session_state[LANGUAGE_KEY] = language
    app.session_state[TERMINOLOGY_KEY] = terms
    app.run().switch_page('story/06_findings.py').run()
    assert not app.exception
    assert len(app.dataframe) == 1 and len(app.dataframe[0].value) == 13
    inventory = app.dataframe[0].value
    assert len(inventory.columns) == 4
    cards = '\n'.join(item.value for item in app.markdown if '<section class="story-card' in item.value)
    assert cards.count('<section class="story-card') == 2
    assert not app.info  # no missing/mismatched-reference substitution
    assert app.session_state[LANGUAGE_KEY] == language
    assert app.session_state[TERMINOLOGY_KEY] == terms
    assert app.button(key='story_previous_6') and app.button(key='story_next_6')
    assert all('sandbox' not in item.proto.url for item in app.get('link_button'))


def test_engineering_missing_reference_discloses_absence_without_inventing_coverage():
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch('app_core.audience_story.load_segment_reference', side_effect=DashboardDataError('reference mismatch')):
        app.switch_page('story/06_findings.py').run()
    assert not app.exception and app.info
    assert not any('<section class="story-card' in item.value for item in app.markdown)
    assert len(app.dataframe[0].value) == 13
    assert app.button(key='story_next_6')
