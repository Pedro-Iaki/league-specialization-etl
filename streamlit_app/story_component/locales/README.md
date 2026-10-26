# Story translation guide

The Streamlit story publishes **Brazilian Portuguese and English**, with all 450
messages translated. Portuguese is the initial language; English remains the
fallback. The header language selector appears beside Terminology. Both catalogs
are marked `ready`. Source documentation and downloadable diagnostic artifacts
retain their original language.

## Files to edit

- `en.json` is the reviewed English source, with 450 stable message IDs.
- `pt-BR.json` has the same IDs and the Brazilian Portuguese translations.
- `manifest.json` controls publication, the initial locale and Intl formatting.
- `../i18n.js` handles fallback, interpolation, plural forms and formatting.
- `../../app_core/story_localization.py` validates the catalogs and supplies host
  startup/recovery copy. The legacy `app_core/i18n.py` is a separate system.

Translate string **values** in `pt-BR.json`. Keep keys unchanged, and save UTF-8.
Do not copy English into untranslated entries: leave `null` until translated.
The checker accepts incomplete drafts; it refuses incomplete published catalogs.

## Copy and terminology

Follow the English meaning and its limits: real behavior, interpreted interests,
simulated purchases, association, eligibility and support. Keep naming feedback
distinct from statistical validation. The audience is a recruiter unfamiliar with
League of Legends; use accessible business language without implying observed
customer spending or causal effects.

Chapter prose, navigation, controls, plots, captions, tooltips, accessibility text,
linked architecture labels, family-method explanations and run-evidence notes all
use this catalog. Guided-question copy lives under `questions.*`; archetype display
names under `archetypes.*`; bands and enum labels under `bands.*` and `labels.*`.
Some keys inherit older function names, but remain stable identifiers. Read the
whole English value for context; do not rename a key to match its translation.

Preserve project/person/character names, source links, filenames, hashes and model
IDs. `A1`–`A8`, family IDs, `Single`/`Blend`/`Diffuse` and canonical query values
remain analytical identifiers. Their **display labels** can be translated through
the catalog. Neither frozen models nor Python question predicates need editing.
The downloadable evidence remains the original English diagnostic artifact;
translated UI explanations do not rewrite source evidence.

## Parameters and formatting

- Keep every `{placeholder}` exactly, including case. You may reorder placeholders
  within a sentence. The checker rejects missing, added or malformed parameters.
- Messages are plain text. Do not insert HTML, JavaScript, CSS or Markdown markup.
  Layout and escaping belong to application code.
- Parameters named `value`, `profiles`, `customers`, `count`, `share`, etc. are
  supplied at runtime. Numbers, percentages, USD currency and UTC dates use Intl
  with the selected locale. Changing locale never converts currency or changes
  the underlying values. Do not manually add separators to these parameters.
- `.one`/`.other` messages such as `purchases.events.*` are grammatical alternatives
  selected through Intl plural rules. Keep the count parameter in both forms.
- Preserve numeric assumptions in explanatory prose (for example 0.20, 1,200,
  annual seasons and eligibility/support floors). Numeric punctuation may follow
  the language; the value and analytical meaning must stay the same.
- Keep short navigation, segment and diagram labels concise. Inspect long labels,
  wrapped buttons, SVG labels and expanded dropdowns at desktop and mobile widths.

## Validate and preview changes

From the repository root, using the existing environment:

```powershell
.venv/Scripts/python.exe streamlit_app/scripts/check_story_locales.py
.venv/Scripts/python.exe -m pytest streamlit_app/tests/test_story_localization.py -q
```

New languages must remain `draft` until complete and reviewed; only then mark
them `ready` in `manifest.json`. Keep `fallbackLocale` as `en`. Portuguese is
already published and configured as `defaultLocale`. Restart Streamlit and
reload the page after editing catalogs.

Verify both languages and both terminology modes. Language switching must retain
the current chapter, question, applied comparison, pending builder edits, selected
family/component, disclosures and scroll position. It must not send an audience
query. Switching during an in-flight query must retain the selected language and
the correct returned audience. Query payloads, category IDs, weights, cash cents
and all denominators must be identical across locales.

The development-only `tests/browser_story_localization.py` injects a synthetic
marked English catalog and uses PT-BR number/date formatting to exercise these
boundaries; it does not write catalog content. It also
checks rendered copy coverage, with source character names/technical identifiers
and formatted timestamps explicitly exempted. See the dashboard launch guide for
the local browser-test prerequisites. Pass `--published` to exercise the actual
Portuguese catalog instead, including language switching with pending edits and
in-flight queries. Pseudo-localization alone cannot establish translation quality.

Portuguese copy is written for a Brazilian reader, rather than following English
sentence structure. Prefer direct questions and concrete actions over literal
phrases such as “públicos interpretados”, “invocação completa” or “concessões”.
Technical terms belong in method explanations when they help explain the result.

Use “classificação competitiva”, “histórico registrado da conta” and “compras
simuladas” consistently. “Avaliado pelo modelo” means a scored profile, not a
validated prediction. Single/Blend/Diffuse display as “Um destaque / Vários
destaques / Sem destaque”; the accompanying explanation defines the 0.20 loading
threshold. These labels do not imply exclusive interests or popularity rankings.
“Interesse principal definido” requires a unique, non-Diffuse maximum. Shared
context is presented as “Filtros comuns a A e B”.

Archetype names are translated display labels; A1–A8 and the reviewed model remain
unchanged. ADCs retains its acronym with a plain explanation. Use the same names
in prose, dropdowns and charts. Check the rendered sentence with its actual
parameters: a catalog can pass structural tests and still read unnaturally.
