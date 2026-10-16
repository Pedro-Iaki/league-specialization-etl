"""Recover a running dashboard whose business helpers predate the current page API."""
from __future__ import annotations

import importlib
import sys
import threading

_RELOAD_LOCK = threading.RLock()

_BUSINESS_API = (
    "CASH_DISCOUNT_COLUMNS", "BUSINESS_PUBLIC_COLUMNS", "EXPERIENCE_METRICS", "TENURE_ORDER", "AUDIENCE_DIMENSIONS",
    "audience_summary", "experience_summary", "cosmetic_summary", "discount_summary",
)
_DEPENDENTS = (
    "app_core.business", "app_core.contracts", "app_core.data", "app_core.business_charts", "app_core.ui",
)


def refresh_legacy_business_helpers() -> bool:
    """Reload an already-cached obsolete API and its consumers in dependency order.

    A source update can leave an earlier business module in a running Streamlit
    process. Importing the new page then fails before a normal rerun can recover.
    Current modules keep their caches.
    """
    with _RELOAD_LOCK:
        business = sys.modules.get("app_core.business")
        if business is None or all(hasattr(business, name) for name in _BUSINESS_API):
            return False
        for name in _DEPENDENTS:
            module = sys.modules.get(name)
            if module is not None:
                importlib.reload(module)
        return True
