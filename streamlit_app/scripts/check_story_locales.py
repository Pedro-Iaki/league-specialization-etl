"""Check story catalog structure and report readiness without publishing a language."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_core.story_localization import load_catalogs

if __name__ == "__main__":
    catalog = load_catalogs()
    for locale in catalog["locales"]:
        values = catalog["messages"][locale["id"]]
        count = sum(value is not None for value in values.values())
        print(f"{locale['id']}: {count}/{len(values)} messages; {locale['status']}")
