import os
import textwrap

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_API       = "https://api.github.com/search/issues"
SO_API           = "https://api.stackexchange.com/2.3/search/advanced"
SO_SITE          = "stackoverflow"

MAX_GITHUB_RESULTS = 3   # top-3 most-relevant issues only
MAX_SO_RESULTS     = 3   # top-3 answered questions only
TIMEOUT_S          = 5   # per-request wall-clock timeout (seconds)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _search_github(query: str) -> list[dict]:
    """
    Returns up to MAX_GITHUB_RESULTS items from GitHub Issues search.
    Each item: {"title": str, "body_excerpt": str, "url": str}.
    Returns [] on any error — never raises.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN", "")
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
            "title":        item.get("title", ""),
            "body_excerpt": textwrap.shorten(body, width=300, placeholder="..."),
            "url":          item.get("html_url", ""),
        })
    return results


def _search_stackoverflow(query: str) -> list[dict]:
    """
    Returns up to MAX_SO_RESULTS items from StackOverflow answered-question search.
    Each item: {"title": str, "answer_excerpt": str, "url": str}.
    Returns [] on any error — never raises.
    """
    params = {
        "order":    "desc",
        "sort":     "relevance",
        "q":        query,
        "answers":  1,           # only questions that have at least 1 answer
        "filter":   "withbody",  # include question body in response
        "site":     SO_SITE,
        "pagesize": MAX_SO_RESULTS,
    }
    key = os.getenv("STACKEXCHANGE_KEY", "")
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
            "title":          item.get("title", ""),
            "answer_excerpt": textwrap.shorten(body, width=300, placeholder="..."),
            "url":            item.get("link", ""),
        })
    return results


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def fetch_external_context(title: str, category: str) -> str:
    """
    Fetches similar GitHub Issues and StackOverflow answers for the given
    defect title and category, and returns a single formatted plain-text
    block ready for prompt injection.

    Args:
        title:    The value of the report's 'title' field (tester_provided).
        category: The bug category string (e.g. "API", "UI", "Performance").

    Returns:
        A formatted string summarising up to MAX_GITHUB_RESULTS GitHub issue
        titles/bodies and up to MAX_SO_RESULTS StackOverflow question excerpts,
        or "" if both sources returned nothing or both calls failed.
        The caller (prompt builder) must treat "" as "no context available"
        and omit the context block from the prompt entirely.

    Never raises. All network errors are caught and logged to stderr.
    Partial results (one source succeeded, the other failed) are returned.
    """
    query = f"{category} bug {title}"

    github_results = _search_github(query)
    so_results     = _search_stackoverflow(query)

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

    return "\n\n".join(sections)  # "" when both lists are empty
