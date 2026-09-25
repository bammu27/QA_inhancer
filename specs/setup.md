# Combined Spec — Unit 0 (app.py) + Unit 1 (Template Loader)

Scope: everything needed to get `streamlit run app.py` showing a working
category selector that resolves and displays the merged template. Nothing
beyond this — no LLM calls yet, no session state for the report object.

**Changes from the previous version of this spec:**
- `optional_fields.json` is dropped entirely — not loaded, not referenced,
  not returned. Optional fields aren't needed at this stage.
- Dropdown now always includes an **"Other"** option in addition to
  whatever category files exist in `extensions/`. Selecting "Other" does
  **not** look for an `extensions/other.json` file — it just returns the
  core fields with no category-specific extension.

---

## 1. Preconditions (already done)

- Folder structure created
- `.env`, `.env.example`, `requirements.txt` in place
- `templates/core_template.json`
- `templates/extensions/api.json`
- `config.py` loading env vars

`templates/optional_fields.json` is no longer needed for this unit — leave
it on disk if it exists (later units may still use it), but Unit 1 code
must not touch it.

If `config.py` is not done yet, minimum needed for this spec only:

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", "templates")
```

---

## 2. File: `pipeline/template_loader.py`

### 2.1 Purpose
Load `core_template.json`, and — if the selected category is a real
extension category — merge in `extensions/{category}.json`. Pure file I/O
+ dict merging. No LLM, no Streamlit imports here.

### 2.2 Function contract

```python
def resolve_template(category: str) -> dict:
    """
    Args:
        category: lowercase category key, e.g. "api" or "other".
                   "other" (and any value not matching a file in
                   extensions/) skips extension loading entirely.

    Returns:
        {
            "category": "api",              # or "other"
            "required_fields": [<core fields> + <category fields, if any>]
        }

    Raises:
        ValueError: if a field name appears in both core and category
                    lists (schema bug — never raised for "other" since
                    there's nothing to merge)
    """
```

Note: `FileNotFoundError` is no longer a real failure path for the normal
flow, since "Other" is always valid and never looks for a file. It can
still surface if `core_template.json` itself is missing — let that
propagate normally, no special handling needed.

### 2.3 Implementation requirements

1. Read `TEMPLATE_DIR` from `config.py` (default `"templates"`), never hardcode the path.
2. Load `{TEMPLATE_DIR}/core_template.json` → `core["fields"]`. Always required.
3. Determine if `category` is `"other"`:
   - If `category == "other"`: skip extension loading. `required_fields = core["fields"]`.
   - Otherwise: load `{TEMPLATE_DIR}/extensions/{category}.json` → `ext["fields"]`,
     and merge as before (`required_fields = core["fields"] + ext["fields"]`,
     with the duplicate-field `ValueError` check).
4. Return the dict with exactly two keys, in this order: `category`, `required_fields`.
5. No `optional_fields` key anywhere in the return value.
6. Cache nothing at this stage — pure function, re-read files each call.

### 2.4 Available categories helper

```python
def list_categories() -> list[str]:
    """
    Scans {TEMPLATE_DIR}/extensions/*.json for category display names
    (filename stem, e.g. "api" -> "API"), sorted alphabetically, then
    appends "Other" as the last entry unconditionally.
    """
```

- Use `pathlib.Path(TEMPLATE_DIR, "extensions").glob("*.json")` for the
  file-backed categories.
- Display-case each stem the same way as before (`.stem.upper()` for
  single-word categories like "api" → "API"; switch to
  `.stem.replace("_", " ").title()` if multiword categories are added later).
- Append `"Other"` at the end regardless of what's in `extensions/` — even
  if the folder is empty, the dropdown must never be empty, since "Other"
  always works.
- Caller (the UI) lowercases the selected label before calling
  `resolve_template` — `"Other"` becomes `"other"`, `"API"` becomes `"api"`,
  which is exactly the sentinel value `resolve_template` checks for in 2.3.

---

## 3. File: `app.py`

### 3.1 Purpose
Minimal Streamlit entrypoint for this stage only: title, category dropdown
(including "Other"), resolved template shown as JSON. No text input, no
LLM, no session state persistence beyond what Streamlit does automatically
on rerun.

### 3.2 Implementation

```python
import streamlit as st
from pipeline.template_loader import resolve_template, list_categories

st.set_page_config(page_title="Defect Description Enhancer", layout="centered")
st.title("Defect Description Enhancer")

categories = list_categories()  # always non-empty: "Other" is guaranteed

selected_category = st.selectbox("Bug category", categories)

try:
    template = resolve_template(selected_category.lower())
except ValueError as e:
    st.error(f"Template schema error: {e}")
    st.stop()

st.subheader("Resolved template")
st.json(template)
```

### 3.3 Notes
- The empty-`extensions/`-folder guard from the previous version is gone —
  it's no longer possible for the dropdown to be empty, since `list_categories()`
  always includes "Other". Simpler `app.py`, one less error branch.
- `FileNotFoundError` handling is dropped for the same reason: the only
  category that reads a file (`extensions/{category}.json`) is guaranteed
  by `list_categories()` to correspond to a file that actually exists;
  "Other" never attempts the read at all.
- No `st.session_state` writes yet — that starts in Unit 2.
- This file will be rewritten incrementally in later units (Unit 8 is the
  final wiring pass) — keep it exactly this thin for now.

---

## 4. Acceptance test (manual, browser)

1. `streamlit run app.py`
2. Page loads with title "Defect Description Enhancer", no traceback.
3. Dropdown shows **"API"** and **"Other"** (API from `extensions/api.json`,
   Other always present).
4. Selecting **"API"** renders a JSON block with:
   - `category: "api"`
   - `required_fields`: the 9 core fields followed by the 5 API fields, 14 total, no duplicates
   - No `optional_fields` key present at all.
5. Selecting **"Other"** renders a JSON block with:
   - `category: "other"`
   - `required_fields`: exactly the 9 core fields, nothing merged in
   - No `optional_fields` key present at all.
6. Temporarily empty out the `extensions/` folder entirely, rerun →
   dropdown shows only "Other", app doesn't crash, selecting it still
   works and returns the 9 core fields.
7. Restore `extensions/api.json` after testing.
8. Manually break the JSON (duplicate a field name between core and api) →
   confirm `st.error` shows the `ValueError` message for "API", while
   "Other" still works fine (since it never touches the broken file).
9. Restore the file after testing.

Once all 9 checks pass, Unit 0 + Unit 1 are complete and Unit 2
(raw text input + LLM #1 extraction) can build on top of `app.py` as-is.