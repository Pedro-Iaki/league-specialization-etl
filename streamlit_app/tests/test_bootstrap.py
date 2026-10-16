from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_running_app_recovers_from_cached_business_module_with_old_api():
    """Reproduce the user's ImportError in an isolated interpreter, then run the app."""
    app_root = Path(__file__).resolve().parents[1]
    script = """
import sys
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
sys.path.insert(0, sys.argv[1])
from app_core import business, contracts, data, business_charts, ui
del business.CASH_DISCOUNT_COLUMNS
try:
    from app_core.business import CASH_DISCOUNT_COLUMNS
except ImportError:
    pass
else:
    raise AssertionError('The stale-module import failure was not reproduced')
from app_core.bootstrap import refresh_legacy_business_helpers
app = AppTest.from_file(str(Path(sys.argv[1]) / 'app.py'), default_timeout=60).run()
assert not app.exception, [error.value for error in app.exception]
assert len(app.get('plotly_chart')) == 4
assert contracts.CASH_DISCOUNT_COLUMNS == business.CASH_DISCOUNT_COLUMNS
assert not refresh_legacy_business_helpers()
with patch('importlib.reload', side_effect=AssertionError('Current modules should not reload')):
    app.run()
assert not app.exception
print('Cached-module recovery and repeat app startup passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(app_root)], capture_output=True, text=True, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cached-module recovery and repeat app startup passed" in result.stdout
