# Technical Specification — Defect Description Enhancer
## (Matches the confirmed workflow exactly: no RAG enrichment, no review gate, auto-send)

Status: Draft v3 — scoped strictly to the workflow you confirmed

## 1. Components

| Component | Job |
| :--- | :--- |
| **Tester UI** | Collects raw text and category through drop down, collects missing-field answers, and hosts the final Markdown review/editor interface |
| **Template Loader** | Resolves which category applies, loads `core_template.json` + the matching `extensions/{category}.json` |
| **LLM #1 — Extraction** | Fills core + category fields it can find in the raw text; flags what it can't |
| **Clarification Loop** | Re-prompts tester for each missing field; accepts either a value or an explicit "unknown" |
| **LLM #2 — Reasoning** | Takes the fully assembled report, tries to fill any still-missing fields (tagged AI-annotated), fills optional fields, writes an optional description + common fixes |
| **Markdown Generator** | Assembles the complete report into a draft Markdown document |
| **QA Review** | Displays the Markdown draft to the QA tester, only review, and holds the report until the tester clicks "Approve & Send" |
| **Email Dispatch** | Sends the final, approved Markdown report to the developer's inbox |



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

`templates/optional_fields.json` (shared, never counted as "missing"):
```json
{
  "fields": ["affected_feature", "workaround", "regression_status",
             "cross_browser_status"]
}
```

### 2.2 Field object (used for every field in the report)

```json
{
  "value": "<string, or null if unfilled>",
  "source": "tester_provided | ai_annotated | missing"
}
```
Three values only — this version has no `ai_inference` /
`ai_reasoning` split; the reasoning LLM's fills are just
`ai_annotated`, matching "show a small message or mark AI annotated"
from your description.

### 2.3 Report object (the thing that moves through the whole pipeline)

```json
{
  "category": "API",
  "core_fields": {
    "title": {"value": "...", "source": "tester_provided"},
    "severity": {"value": null, "source": "missing"}
  },
  "category_fields": {
    "endpoint": {"value": "...", "source": "tester_provided"},
    "status_code": {"value": "500", "source": "ai_annotated"}
  },
  "optional_fields": {
    "workaround": {"value": "...", "source": "ai_annotated"}
  },
  "developer_notes": {
    "description": "<LLM #2's written summary>",
    "common_fixes": ["...", "..."]
  }
}
```

## 3. Component Contracts

### 3.1 Template Loader
```python
def resolve_template(category: str) -> dict:
    """Returns {"required_fields": core + category fields,
                "optional_fields": optional fields}"""
```

### 3.2 LLM #1 — Extraction
```python
def extract_fields(raw_text: str, template: dict) -> dict:
    """Returns report_object with core_fields + category_fields filled
       where found, source='tester_provided'; source='missing' elsewhere.
       One LLM call. Code-level check afterward: every required field
       appears exactly once, either filled or missing — never both,
       never neither."""
```

### 3.3 Clarification Loop (UI-driven, no LLM call)
```python
### 3.3 Clarification Loop (LLM-assisted Extraction)
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

### 3.4 LLM #2 — Reasoning
```python
def reason_and_annotate(report: dict) -> dict:
    """One LLM call over the full report object (fields + their current
       source tags, missing ones included).
       - Any field still 'missing' that this call can infer gets filled,
         source='ai_annotated'.
       - Fields already 'tester_provided' are NEVER modified — enforce
         with a code-level diff check before/after this call, don't
         just trust the prompt.
       - optional_fields get filled opportunistically the same way.
       - developer_notes.description and .common_fixes are written here."""
```

### 3.5 Markdown Generator (no LLM call — pure formatting)
```python
def render_markdown(report: dict) -> str:
    """Assembles the finalized report dictionary into a complete Markdown document.
       - tester_provided fields render plain.
       - ai_annotated fields render with an inline marker, e.g. '(AI annotated)'.
       - Optional description + common fixes render as their own section at the end.
       Returns final_markdown string."""
```

### 3.6 QA Review (UI-driven, no editing)
```python
def review_and_approve(markdown: str) -> bool:
    """Displays the rendered Markdown in the UI for the QA tester to review.
       The tester verifies the document and clicks 'Approve & Send'.
       Returns True upon confirmation (or False if cancelled)."""
```

### 3.7 Email Dispatch
```python
def send_report(markdown: str, developer_email: str) -> dict:
    """Sends the reviewed and approved Markdown report to the developer's inbox.
       Triggered immediately upon QA confirmation.
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
                 reason_and_annotate(report)  # LLM #2
                           │
                           ▼
                 render_markdown(report)
                           │
                           ▼
                 [UI Review Step: review_and_approve()]
                           │
                           ▼
                 send_report(markdown, developer_email)
```

## 5. Tech Stack

# 5. Tech Stack

| Layer | Choice | Why |
| --- | --- | --- |
| **Frontend & App Host** | **Streamlit** | Acts as both UI and application backend. Manages pipeline state across steps via `st.session_state` and executes pipeline functions directly without needing FastAPI or separate REST API endpoints. |
| **LLM Access** | **`groq` (Native Python SDK)** | Direct integration with Groq models for ultra-fast inference speeds. Eliminates abstraction dependencies like `litellm`. |
| **Template Storage** | **Flat JSON files (`templates/`)** | Loads `core_template.json` and `extensions/{category}.json` directly from disk using standard Python `json`. Zero database overhead. |
| **Category Selection** | **UI Dropdown (`st.selectbox`)** | Tester explicitly selects the bug category in the UI. Eliminates extra classification LLM calls and vector stores (e.g., ChromaDB). |
| **Data Validation & Integrity** | **Plain Python / Pydantic** | Enforces field source tracking (`tester_provided`, `ai_annotated`, `missing`) and performs code-level diff checks ensuring LLM #2 never mutates human-provided data. |
| **Markdown Generator** | **Jinja2 (or Python f-strings)** | Pure string templating that converts the finalized report dictionary into Markdown without an extra LLM call. Rendered live in the UI via `st.markdown()`. |
| **Delivery** | **`smtplib` (Python Standard Library)** | Direct SMTP email dispatch, triggered exclusively when the QA tester clicks "Approve & Send" in the Streamlit interface. |
| **Testing Strategy** | **Manual Iterative Testing (Browser)** | Validates UI state transitions, clarification prompts, and LLM output directly in the browser. Omits `pytest` suites to conserve Antigravity AI agent context and token limits during early feature churn. |



## 6. Non-Functional Rules

1. **Strict Field Tagging**: Every field in the report object is strictly tagged as `tester_provided` XOR `ai_annotated` XOR `missing` — never ambiguous, enforced by code-level validation after every pipeline stage.
2. **Immutability of Human Input**: `reason_and_annotate` (LLM #2) may only fill fields currently marked as `missing`, or generate `optional_fields` and `developer_notes`. It can **never** overwrite or alter an existing `tester_provided` value. This is strictly enforced via a code-level pre/post diff check, not by prompt instructions alone.
3. **Clarification Extraction & Finality**: Clarification inputs are provided as freeform natural language descriptions and parsed via a targeted LLM #1 extraction call. If the tester explicitly states "I don't know" / "skip" or if the targeted extraction finds no value for a missing field, that field permanently stays tagged as `missing` and is never re-prompted. It moves directly to LLM #2 for potential AI reasoning.
4. **Gated Delivery**: Email dispatch is never automatic upon Markdown generation. Dispatch occurs **only** after the QA tester reviews the rendered Markdown in the Streamlit UI and explicitly clicks "Approve & Send".

---

## 7. Explicitly Out of Scope

- **No Markdown Inline Editing**: The QA Review step is a read-only preview and approval gate ("Approve & Send"). The tester does not manually edit raw Markdown text in the UI.
- **No Separate API Backend (FastAPI)**: Streamlit hosts both the frontend UI and the pipeline execution logic using native Python and `st.session_state`.
- **No Vector DB / RAG / Historical Ticket Retrieval**: The bug category is selected directly via a UI dropdown (`st.selectbox`); templates are merged dynamically from local JSON files (`templates/`).
- **No Automated Test Suites (`pytest`)**: Application testing is conducted via manual iterative browser testing to conserve Antigravity AI coding agent context and token limits during early feature development.
- **No External Database Persistence**: Report state lives in memory during the active Streamlit session and is dispatched via SMTP email; no SQL or NoSQL database is required.