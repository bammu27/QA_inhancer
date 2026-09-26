# Technical Specification — Defect Description Enhancer

Status: scoped to the confirmed workflow — tester-driven extraction,
clarification, external reference lookup, AI reasoning, Markdown
generation, a manual review gate, and gated email dispatch. No vector DB,
no embeddings, no historical-ticket retrieval, no fine-tuning on past
reports, and no automatic send without explicit tester approval.

---

## 1. Components

| Component | Job |
| :--- | :--- |
| **Tester UI** | Collects raw text and category through drop down, collects missing-field answers, and hosts the final Markdown review interface |
| **Template Loader** | Resolves which category applies, loads `core_template.json` + the matching `extensions/{category}.json` |
| **LLM #1 — Extraction** | Fills core + category fields it can find in the raw text; flags what it can't |
| **Clarification Loop** | Re-prompts tester for each missing field; accepts either a value or an explicit "unknown" |
| **External Reference Search** | Queries the GitHub Issues API and the Stack Exchange (Stack Overflow) API for existing issues/questions that look related to the confirmed fields; returns a short list of titles + links, no scraping of full page content |
| **LLM #2 — Reasoning** | Takes the fully assembled report plus the reference search results, tries to fill any still-missing fields (tagged AI-annotated), writes a description + common fixes that may cite the found references |
| **Markdown Generator** | Assembles the complete report — including a "Related Issues / Discussions" section sourced from the reference search — into a draft Markdown document |
| **QA Review** | Displays the Markdown draft to the QA tester, only review, and holds the report until the tester clicks "Approve & Send" |
| **Email Dispatch** | Sends the final, approved report to the developer's inbox |

---

## 2. Data Schemas

### 2.1 Template files

`templates/core_template.json`:
```json
{
  "fields": ["title", "severity", "priority", "environment",
             "steps_to_reproduce", "expected_result", "actual_result",
             "frequency", "evidence"]
}
```

`templates/extensions/api.json` (one file per category):
```json
{
  "category": "API",
  "fields": ["endpoint", "http_method", "request_payload",
             "response_payload", "status_code"]
}
```

### 2.2 Field object (used for every field in the report)

```json
{
  "value": "<string, or null if unfilled>",
  "source": "tester_provided | ai_annotated | missing"
}
```
Three values only.

### 2.3 Reference object

One entry per result returned by the External Reference Search
component, for either source:

```json
{
  "source": "github" | "stackoverflow",
  "title": "<issue or question title, verbatim from the API>",
  "url": "<direct link to the issue/question>",
  "score_or_state": "<GitHub: issue state ('open'/'closed'); Stack Overflow: answer/vote count as a string, e.g. '3 answers'>"
}
```

No snippet, excerpt, or body text is stored — title + link + one small
status signal only. This keeps the object tiny and sidesteps any
copyright/reproduction concern around quoting third-party issue or answer
bodies; the tester/developer clicks through to read the source themselves.

### 2.4 Report object (the thing that moves through the whole pipeline)

```json
{
  "category": "API",
  "fields": {
    "title": {"value": "...", "source": "tester_provided"},
    "severity": {"value": null, "source": "missing"},
    "endpoint": {"value": "...", "source": "tester_provided"},
    "status_code": {"value": "500", "source": "ai_annotated"}
  },
  "external_references": {
    "github_issues": [
      {"source": "github", "title": "...", "url": "...", "score_or_state": "open"}
    ],
    "stackoverflow": [
      {"source": "stackoverflow", "title": "...", "url": "...", "score_or_state": "3 answers"}
    ]
  },
  "developer_notes": {
    "description": "<LLM #2's written summary, may reference the items above by title>",
    "common_fixes": ["...", "..."]
  }
}
```

`external_references` is always present once the search step has run —
either source's list may be empty (`[]`) if nothing relevant was found;
it is never omitted or null. `fields` stays flat — no
`core_fields`/`category_fields` split, no `optional_fields`.

---

## 3. Component Contracts

### 3.1 Template Loader
```python
def resolve_template(category: str) -> dict:
    """Returns {"category": str, "required_fields": core + category fields}"""
```

### 3.2 LLM #1 — Extraction
```python
def extract_fields(raw_text: str, template: dict) -> dict:
    """Returns report_object with fields filled where found,
       source='tester_provided'; source='missing' elsewhere.
       One LLM call. Code-level check afterward: every required field
       appears exactly once, either filled or missing — never both,
       never neither."""
```

### 3.3 Clarification Loop (LLM-assisted Extraction)
```python
def extract_clarifications(
    missing_fields: list[str],
    user_input_text: str
) -> dict[str, str]:
    """Targeted LLM #1 call.
       Parses freeform natural language text supplied by the QA tester
       specifically for keys in missing_fields.

       - Extracted values → merged into report with source='tester_provided'.
       - If input is 'unknown'/'skip' or key is absent → field remains source='missing'
         and is permanently locked from further QA prompting this session.
    """
```

### 3.4 External Reference Search
```python
def search_external_references(report: dict) -> dict:
    """
    Builds one search query from the report's tester_provided fields
    (title + a short excerpt of steps_to_reproduce/actual_result — never
    the full report dump, to keep queries short and relevant), then:

    - Calls the GitHub Issues Search API (GET /search/issues), scoped to
      issues only (not PRs), sorted by relevance, top 3 results.
    - Calls the Stack Exchange API (GET /2.3/search/advanced against
      site=stackoverflow), top 3 results, sorted by relevance.

    Returns:
        {"github_issues": [<reference object>, ...],
         "stackoverflow": [<reference object>, ...]}

    Never raises. Any HTTP failure, timeout, rate-limit response, or
    missing API credential for either source degrades that source to an
    empty list — the pipeline must be able to proceed to LLM #2 with
    zero external results if both APIs are unreachable. This is a
    best-effort enrichment step, not a required one.
    """
```

### 3.5 LLM #2 — Reasoning
```python
def reason_and_annotate(report: dict) -> dict:
    """One LLM call over the full report object (fields + their current
       source tags, missing ones included) PLUS report["external_references"]
       as additional read-only context.
       - Any field still 'missing' that this call can infer gets filled,
         source='ai_annotated'.
       - Fields already 'tester_provided' are NEVER modified — enforce
         with a code-level diff check before/after this call, don't
         just trust the prompt.
       - external_references is NEVER modified by this call either — same
         diff-check treatment as tester_provided fields, since it was
         populated by a separate, already-completed component.
       - developer_notes.description and .common_fixes are written here,
         and may reference titles from external_references by name (e.g.
         "similar to GitHub issue #1234") — but the reference list itself
         (titles/urls) is carried through unchanged, never rewritten or
         re-summarized by the LLM.
    """
```

### 3.6 Markdown Generator (no LLM call — pure formatting)
```python
def render_markdown(report: dict) -> str:
    """Assembles the finalized report dictionary into a complete Markdown
       document.
       - tester_provided fields render plain.
       - ai_annotated fields render with an inline marker, e.g. '(AI annotated)'.
       - A 'Related Issues / Discussions' section renders after Developer
         Notes, listing each external_references entry as a Markdown link
         with its source and score_or_state; omitted entirely if both
         lists are empty (not rendered as an empty heading).
       Returns final_markdown string."""
```

### 3.7 QA Review (UI-driven, no editing)
```python
def review_and_approve(decision: str) -> bool:
    """Records the tester's Approve/Cancel click. Returns True for
       approve, False for cancel."""
```

### 3.8 Email Dispatch
```python
def send_report(markdown_text: str, developer_email: str) -> dict:
    """Sends the reviewed and approved report to the developer's inbox as
       a multipart email (HTML + plain-text fallback) with the raw .md
       attached verbatim. Triggered immediately upon QA confirmation.
       Returns {"status": "sent"|"failed", ...}."""
```

---

## 4. Pipeline Flow (function-call order)

```text
raw_text + category
  │
  ▼
resolve_template(category)
  │
  ▼
extract_fields(raw_text, template)  # LLM #1 Pass 1
  │
  ▼
[UI Clarification Loop] ──(QA types freeform text)──> extract_clarifications() # LLM #1 Targeted Pass
  │                                                        │
  └────────────────────────┬───────────────────────────────┘
                           │ (All required fields are now 'tester_provided' or permanently 'missing')
                           ▼
                 search_external_references(report)   # GitHub + Stack Overflow
                           │  (best-effort; empty lists on failure, never blocks)
                           ▼
                 reason_and_annotate(report)  # LLM #2, reads external_references too
                           │
                           ▼
                 render_markdown(report)   # includes "Related Issues / Discussions"
                           │
                           ▼
                 [UI Review Step: review_and_approve()]
                           │
                           ▼
                 send_report(markdown, developer_email)
```

---

## 5. Tech Stack

| Layer | Choice | Why |
| --- | --- | --- |
| **Frontend & App Host** | **Streamlit** | Acts as both UI and application backend. Manages pipeline state across steps via `st.session_state` and executes pipeline functions directly without needing FastAPI or separate REST API endpoints. |
| **LLM Access** | **`groq` (Native Python SDK)** | Direct integration with Groq models for ultra-fast inference speeds. Eliminates abstraction dependencies like `litellm`. |
| **Template Storage** | **Flat JSON files (`templates/`)** | Loads `core_template.json` and `extensions/{category}.json` directly from disk using standard Python `json`. Zero database overhead. |
| **Category Selection** | **UI Dropdown (`st.selectbox`)** | Tester explicitly selects the bug category in the UI. Eliminates extra classification LLM calls and vector stores. |
| **External Reference Search** | **`requests` against GitHub REST API v3 + Stack Exchange API v2.3** | Both are free, public, keyless-for-low-volume REST APIs — no SDK dependency needed, no vector store, no scraping. Optional API tokens raise rate limits but are not required to function. |
| **Data Validation & Integrity** | **Plain Python / Pydantic** | Enforces field source tracking (`tester_provided`, `ai_annotated`, `missing`) and performs code-level diff checks ensuring LLM #2 never mutates human-provided data or the external reference list. |
| **Markdown Generator** | **Jinja2 (or Python f-strings)** | Pure string templating that converts the finalized report dictionary into Markdown without an extra LLM call. Rendered live in the UI via `st.markdown()`. |
| **Delivery** | **`smtplib` (Python Standard Library)**, HTML rendering via **`markdown`** | Multipart SMTP email (HTML + plain-text + raw `.md` attachment), triggered exclusively when the QA tester clicks "Approve & Send" in the Streamlit interface. |
| **Testing Strategy** | **Manual Iterative Testing (Browser)** | Validates UI state transitions, clarification prompts, external search results, and LLM output directly in the browser. Omits `pytest` suites to conserve agent context and token limits during early feature churn. |

### 5.1 `.env` additions

```
# --- External Reference Search (optional but recommended) ---
GITHUB_TOKEN=
STACKEXCHANGE_KEY=
EXTERNAL_SEARCH_TIMEOUT_SECONDS=8
EXTERNAL_SEARCH_RESULTS_PER_SOURCE=3
```

Both keys are optional — the GitHub Search API and Stack Exchange API
both serve unauthenticated requests at a lower rate limit (60 req/hr for
GitHub unauthenticated vs. 5,000/hr authenticated; Stack Exchange allows
300 req/day per IP without a key). For a QA tool used by a small team,
unauthenticated is usually fine to start; add the keys if the team hits
rate limits.

---

## 6. Non-Functional Rules

1. **Strict Field Tagging**: Every field in the report object is strictly tagged as `tester_provided` XOR `ai_annotated` XOR `missing` — never ambiguous, enforced by code-level validation after every pipeline stage.
2. **Immutability of Human Input**: `reason_and_annotate` (LLM #2) may only fill fields currently marked as `missing`, or generate `developer_notes`. It can **never** overwrite or alter an existing `tester_provided` value. This is strictly enforced via a code-level pre/post diff check, not by prompt instructions alone.
3. **Clarification Extraction & Finality**: Clarification inputs are provided as freeform natural language descriptions and parsed via a targeted LLM #1 extraction call. If the tester explicitly states "I don't know" / "skip" or if the targeted extraction finds no value for a missing field, that field permanently stays tagged as `missing` and is never re-prompted. It moves directly to external reference search and then LLM #2 for potential AI reasoning.
4. **Gated Delivery**: Email dispatch is never automatic upon Markdown generation. Dispatch occurs **only** after the QA tester reviews the rendered Markdown in the Streamlit UI and explicitly clicks "Approve & Send".
5. **External Search Never Blocks**: A failure, timeout, or rate-limit response from either GitHub or Stack Exchange results in an empty list for that source — never an exception that halts the pipeline, and never a retry loop that stalls the UI. The tester should never be unable to complete a report because a third-party API is down.
6. **External References Are Read-Only Once Fetched**: Once `search_external_references` returns, `report["external_references"]` is treated exactly like a `tester_provided` field for immutability purposes — `reason_and_annotate` may read and cite it, but a code-level diff check confirms it is byte-identical before and after the LLM #2 call.
7. **No Content Scraping**: Only title, URL, and a short status signal (state/answer-count) are stored per reference — never the full issue/question body or comments. This keeps the feature to lightweight linking, not content reproduction.

---

## 7. Explicitly Out of Scope

- **No Markdown Inline Editing**: The QA Review step is a read-only preview and approval gate ("Approve & Send"). The tester does not manually edit raw Markdown text in the UI.
- **No Separate API Backend (FastAPI)**: Streamlit hosts both the frontend UI and the pipeline execution logic using native Python and `st.session_state`.
- **No Vector DB / Embeddings / Historical-Ticket Retrieval**: External Reference Search (Section 3.4) is a live keyword query against two public REST APIs, not a retrieval system over an internal corpus — building a vector store or fine-tuning on the team's own past reports remains out of scope.
- **No Automated Test Suites (`pytest`)**: Application testing is conducted via manual iterative browser testing to conserve agent context and token limits during early feature development.
- **No External Database Persistence**: Report state lives in memory during the active Streamlit session and is dispatched via SMTP email; no SQL or NoSQL database is required.
- **No Full-Text Fetch of GitHub/Stack Overflow Content**: Only search-result metadata (title, URL, state/answer-count) is retrieved — no fetching of full issue threads, comments, or accepted-answer bodies.