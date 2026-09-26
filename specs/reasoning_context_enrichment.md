# Spec — Unit 4b: Reasoning Context Enrichment (GitHub Issues + StackOverflow)

Scope: upgrade the existing `reason_and_annotate` pipeline (Unit 4) to fetch
real-world external context — similar GitHub Issues and StackOverflow answers —
**before** the Groq reasoning call, and inject that context into the prompt so
the LLM produces richer, more actionable `developer_notes`.

This spec is purely additive. It does **not** change any Unit 4 invariant:
`tester_provided` immutability, the diff-check, the idempotency guard, or
the Pydantic schema. Every existing acceptance test from Unit 4 must still
pass unchanged after this upgrade.

Builds on: `pipeline/llm_reasoning.py`, `prompts/reasoning_prompt.py`,
`utils/groq_client.py`, `config.py`, and `.env` from Units 0–4.

---

## 1. Preconditions

- Unit 4 complete and all 8 acceptance tests passing.
- Internet access available from the runtime environment (the Streamlit
  process can reach `api.github.com` and `api.stackexchange.com` over HTTPS).
- No new mandatory API keys for the default path:
  - GitHub public search works unauthenticated (60 req/h). A `GITHUB_TOKEN`
    may be added to `.env` to raise the cap to 5,000 req/h — optional.
  - StackExchange search API is unauthenticated (300 req/day free). A
    `STACKEXCHANGE_KEY` may be added to raise the cap — optional.
- `requests` library is already transitively present; add it explicitly to
  `requirements.txt` so the dependency is declared.

```
# requirements.txt — addition
requests>=2.31.0
```

---

## 2. New file: `utils/context_fetcher.py`

This module owns all external HTTP calls. It is deliberately isolated from
the LLM layer so it can be tested, mocked, or disabled independently.

### 2.1 Public interface

```python
def fetch_external_context(title: str, category: str) -> str:
    """
    Fetches similar GitHub Issues and StackOverflow answers for the given
    defect title and category, and returns a single formatted plain-text
    block ready for prompt injection.

    Args:
        title:    The value of the report's 'title' field (tester_provided).
        category: The bug category string (e.g. "API", "UI", "Performance").

    Returns:
        A non-empty string summarising up to MAX_GITHUB_RESULTS GitHub issue
        titles + bodies and up to MAX_SO_RESULTS StackOverflow answer excerpts,
        or an empty string "" if both sources returned nothing or both calls
        failed — the caller (prompt builder) must treat "" as "no context
        available" and omit the context block from the prompt entirely.

    Never raises. All network errors are caught and logged to stderr; partial
    results (one source succeeded, the other failed) are still returned.
    """
```

### 2.2 GitHub Issues search

```python
import os, requests, textwrap

GITHUB_API = "https://api.github.com/search/issues"
MAX_GITHUB_RESULTS = 3   # top-3 most-relevant issues only
TIMEOUT_S = 5            # per-request wall-clock timeout

def _search_github(query: str) -> list[dict]:
    """
    Returns up to MAX_GITHUB_RESULTS items from GitHub issue search.
    Each item: {"title": str, "body_excerpt": str, "url": str}.
    Returns [] on any error.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(
            GITHUB_API,
            params={
                "q": f"{query} is:issue",
                "sort": "relevance",
                "per_page": MAX_GITHUB_RESULTS,
            },
            headers=headers,
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception as exc:
        print(f"[context_fetcher] GitHub search failed: {exc}", flush=True)
        return []

    results = []
    for item in items[:MAX_GITHUB_RESULTS]:
        body = (item.get("body") or "").strip()
        results.append({
            "title": item.get("title", ""),
            "body_excerpt": textwrap.shorten(body, width=300, placeholder="..."),
            "url": item.get("html_url", ""),
        })
    return results
```

**Query construction rule** — build the search query inside
`fetch_external_context`, not inside `_search_github`:

```python
query = f"{category} bug {title}"
```

Simple concatenation is sufficient; do not attempt NLP pre-processing.

### 2.3 StackOverflow search

```python
SO_API = "https://api.stackexchange.com/2.3/search/advanced"
MAX_SO_RESULTS = 3    # top-3 answered questions only
SO_SITE = "stackoverflow"

def _search_stackoverflow(query: str) -> list[dict]:
    """
    Returns up to MAX_SO_RESULTS items from the StackOverflow answered-questions
    search. Each item: {"title": str, "answer_excerpt": str, "url": str}.
    Returns [] on any error.
    """
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "answers": 1,          # only questions that have at least 1 answer
        "filter": "withbody",  # include question body in response
        "site": SO_SITE,
        "pagesize": MAX_SO_RESULTS,
    }
    key = os.getenv("STACKEXCHANGE_KEY")
    if key:
        params["key"] = key

    try:
        resp = requests.get(SO_API, params=params, timeout=TIMEOUT_S)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception as exc:
        print(f"[context_fetcher] StackOverflow search failed: {exc}", flush=True)
        return []

    results = []
    for item in items[:MAX_SO_RESULTS]:
        body = (item.get("body") or "").strip()
        results.append({
            "title": item.get("title", ""),
            "answer_excerpt": textwrap.shorten(body, width=300, placeholder="..."),
            "url": item.get("link", ""),
        })
    return results
```

### 2.4 `fetch_external_context` — assembly

```python
def fetch_external_context(title: str, category: str) -> str:
    query = f"{category} bug {title}"

    github_results  = _search_github(query)
    so_results      = _search_stackoverflow(query)

    sections: list[str] = []

    if github_results:
        lines = ["GitHub Issues (similar reports):"]
        for i, r in enumerate(github_results, 1):
            lines.append(f"  {i}. {r['title']}")
            if r["body_excerpt"]:
                lines.append(f"     {r['body_excerpt']}")
        sections.append("\n".join(lines))

    if so_results:
        lines = ["StackOverflow (related questions):"]
        for i, r in enumerate(so_results, 1):
            lines.append(f"  {i}. {r['title']}")
            if r["answer_excerpt"]:
                lines.append(f"     {r['answer_excerpt']}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)   # "" if both lists were empty
```

---

## 3. Changes to `config.py`

Add two optional environment variable reads. Neither is required; both
default to `""` so the module skips auth headers when keys are absent.

```python
# config.py — additions
GITHUB_TOKEN              = os.getenv("GITHUB_TOKEN", "")
STACKEXCHANGE_KEY         = os.getenv("STACKEXCHANGE_KEY", "")

# Optional: allow disabling external calls entirely (e.g., offline dev mode)
CONTEXT_ENRICHMENT_ENABLED = os.getenv("CONTEXT_ENRICHMENT_ENABLED", "true").lower() == "true"
```

---

## 4. Changes to `.env`

Append the three optional vars. Leave values blank if not yet obtained;
the pipeline degrades gracefully to unauthenticated calls.

```dotenv
# --- External Context Enrichment (Unit 4b) ---
GITHUB_TOKEN=
STACKEXCHANGE_KEY=
CONTEXT_ENRICHMENT_ENABLED=true
```

---

## 5. Changes to `prompts/reasoning_prompt.py`

### 5.1 Updated function signature

```python
def build_reasoning_messages(report: dict, external_context: str = "") -> list[dict]:
```

The `external_context` parameter defaults to `""` so every existing call
site that does **not** pass it continues to work without modification.

### 5.2 Prompt injection rule

Inject the context block into the **user prompt only**, between the
confirmed-fields block and the missing-fields block, but **only when
`external_context` is non-empty**:

```python
context_block = ""
if external_context.strip():
    context_block = (
        f"External context retrieved from GitHub and StackOverflow "
        f"(use this to write better developer_notes and common_fixes — "
        f"do NOT use it to infer field values unless it directly states "
        f"the missing value unambiguously):\n"
        f"{external_context}\n\n"
    )

user_prompt = (
    f"Bug category: {report['category']}\n\n"
    f"Confirmed fields (context only — do NOT include these in your "
    f"output, they are already final):\n"
    f"{json.dumps(tester_provided, indent=2)}\n\n"
    f"{context_block}"                          # inserted here, "" when absent
    f"Fields still missing (infer a value ONLY if the confirmed "
    f"fields above genuinely support a specific inference; otherwise "
    f"leave as null — do not guess vague filler like \"unknown\" or "
    f"\"N/A\"):\n"
    f"{json.dumps(missing)}\n\n"
    # ... rest of prompt unchanged ...
)
```

### 5.3 System prompt addition

Append one sentence to the existing system prompt to set the model's
expectation about the new context block:

```
"When external context from GitHub or StackOverflow is provided, "
"use it to write more specific and actionable developer_notes and "
"common_fixes. Do not blindly repeat it — synthesise it with the "
"confirmed fields to produce a concise, developer-facing summary."
```

---

## 6. Changes to `pipeline/llm_reasoning.py`

### 6.1 Import

```python
from utils.context_fetcher import fetch_external_context
import config
```

### 6.2 Fetch step — inserted between idempotency guard and `build_reasoning_messages`

```python
def reason_and_annotate(report: dict) -> dict:
    original_fields = copy.deepcopy(report["fields"])

    # --- existing idempotency guard (unchanged) ---
    if report.get("developer_notes") is not None:
        raise LLMReasoningError(
            "reason_and_annotate called on a report that already has "
            "ai_annotated fields. Refusing to run twice on the same report."
        )

    missing_keys = [k for k, v in original_fields.items() if v["source"] == "missing"]

    # --- NEW: fetch external context before building the prompt ---
    external_context = ""
    if config.CONTEXT_ENRICHMENT_ENABLED:
        title_field = original_fields.get("title", {})
        title_value = title_field.get("value") or ""
        if title_value:                          # only fetch when title exists
            external_context = fetch_external_context(
                title=title_value,
                category=report.get("category", ""),
            )
        # If title is missing or fetch returned "", external_context stays "".
        # The prompt builder handles "" by omitting the context block entirely.

    # --- existing prompt build (signature extended, default "" preserves compat) ---
    messages = build_reasoning_messages(report, external_context=external_context)

    # ... rest of function unchanged from Unit 4 spec ...
```

**Key constraint**: the fetch step is non-blocking from the caller's
perspective — `fetch_external_context` never raises (see Section 2.1).
A total network failure simply results in `external_context = ""` and the
reasoning call proceeds exactly as it did before this upgrade.

---

## 7. Non-negotiable invariants

All Unit 4 invariants are inherited unchanged:

1. `tester_provided` fields are never read for modification or written by
   the reasoning LLM. The diff-check (`assert_tester_provided_unchanged`)
   runs on every call regardless of whether context was fetched.
2. `annotated_fields` keys must be exactly the missing-fields set — not
   influenced by external context in any way.
3. `developer_notes.description` must be non-empty. The enrichment raises
   the floor of quality, not the acceptance bar — the existing Pydantic
   validation is the gate, not the content of the external data.
4. Idempotency guard remains: calling `reason_and_annotate` twice on the
   same report still raises `LLMReasoningError` even if external context
   would now differ.
5. `CONTEXT_ENRICHMENT_ENABLED=false` in `.env` disables all HTTP calls
   completely — the function behaves identically to the pre-upgrade Unit 4
   implementation. This is the offline / rate-limit-exhausted escape hatch.

---

## 8. Rate-limit and failure behaviour

| Condition | Behaviour |
| :--- | :--- |
| GitHub unauthenticated (60 req/h exhausted) | `_search_github` returns `[]`; SO results (if any) still used |
| SO API quota (300 req/day) exhausted | `_search_stackoverflow` returns `[]`; GitHub results (if any) still used |
| Both APIs return `[]` | `external_context = ""`; prompt has no context block; LLM call proceeds as Unit 4 |
| Network timeout (TIMEOUT_S = 5) | Caught, logged to stderr, treated as `[]` |
| `title` field is `missing` | Fetch skipped entirely; `external_context = ""` |
| `CONTEXT_ENRICHMENT_ENABLED=false` | Fetch skipped entirely; `external_context = ""` |

No retry logic inside `context_fetcher.py`. One attempt per source per
`reason_and_annotate` call. Retries would extend the UI spinner beyond
acceptable latency for a Streamlit session.

---

## 9. Acceptance tests (manual, browser)

Run these **after** all 8 Unit 4 acceptance tests still pass on the upgraded codebase.

| # | Setup | Action | Expected |
| :--- | :--- | :--- | :--- |
| **4b-1** | Normal session, `CONTEXT_ENRICHMENT_ENABLED=true`, title filled | Click **Run AI Reasoning** | Spinner completes; `developer_notes.description` references concepts beyond the raw confirmed fields |
| **4b-2** | `title` field is `missing` (locked from Unit 3) | Click **Run AI Reasoning** | No HTTP calls made; reasoning completes normally; no error |
| **4b-3** | Set `CONTEXT_ENRICHMENT_ENABLED=false` in `.env`, restart | Click **Run AI Reasoning** | No HTTP calls; output identical in structure to pre-upgrade Unit 4 output |
| **4b-4** | Block outbound HTTP (disconnect network) | Click **Run AI Reasoning** | `context_fetcher` logs errors to stderr; `external_context = ""`; reasoning call still completes; no `st.error` shown to user |
| **4b-5** | Valid session with context fetched | Click **Run AI Reasoning** a second time | `st.info("AI reasoning has already run...")` fires — idempotency guard unchanged |
| **4b-6** | Inspect `st.session_state["report"]` in before/after panels | Compare `tester_provided` fields | Byte-identical before and after — diff-check still enforced |

Test **4b-4** is the most important new test: it proves the enrichment is
purely additive and never breaks the happy path when external calls fail.

---

## 10. Files changed / created — summary

| File | Change type | What changes |
| :--- | :--- | :--- |
| `utils/context_fetcher.py` | **New** | GitHub + SO fetch logic, `fetch_external_context` |
| `config.py` | **Edit** | Add `GITHUB_TOKEN`, `STACKEXCHANGE_KEY`, `CONTEXT_ENRICHMENT_ENABLED` |
| `.env` | **Edit** | Add three optional vars (blank by default) |
| `prompts/reasoning_prompt.py` | **Edit** | Accept `external_context` param; inject context block; extend system prompt |
| `pipeline/llm_reasoning.py` | **Edit** | Import and call `fetch_external_context`; pass result to `build_reasoning_messages` |
| `requirements.txt` | **Edit** | Add `requests>=2.31.0` |
