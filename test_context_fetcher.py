"""
Quick test script — verifies GitHub Issues and StackOverflow API calls
are working from context_fetcher.py.

Run from the project root:
    python test_context_fetcher.py
"""

import sys
import os
import io

# Force UTF-8 output — GitHub/SO titles often contain emoji and special chars
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Make sure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from utils.context_fetcher import _search_github, _search_stackoverflow, fetch_external_context

DIVIDER = "=" * 65
SAMPLE_TITLE    = "POST /api/login returns 500 on valid credentials"
SAMPLE_CATEGORY = "API"

# ── TEST 1: GitHub Issues ────────────────────────────────────────────────────
print(DIVIDER)
print("TEST 1 — GitHub Issues search")
print(DIVIDER)

gh_results = _search_github(f"{SAMPLE_CATEGORY} bug {SAMPLE_TITLE}")

if gh_results:
    print(f"  Found {len(gh_results)} result(s):\n")
    for i, r in enumerate(gh_results, 1):
        title   = r.get("title", "—")
        excerpt = r.get("body_excerpt", "")[:120]
        url     = r.get("url", "")
        print(f"  [{i}] {title}")
        print(f"       Excerpt : {excerpt}")
        print(f"       URL     : {url}")
        print()
else:
    print("  No results returned (rate-limited or API failed — check stderr above)\n")

# ── TEST 2: StackOverflow ────────────────────────────────────────────────────
print(DIVIDER)
print("TEST 2 — StackOverflow search")
print(DIVIDER)

so_results = _search_stackoverflow(f"{SAMPLE_CATEGORY} bug {SAMPLE_TITLE}")

if so_results:
    print(f"  Found {len(so_results)} result(s):\n")
    for i, r in enumerate(so_results, 1):
        title   = r.get("title", "—")
        excerpt = r.get("answer_excerpt", "")[:120]
        url     = r.get("url", "")
        print(f"  [{i}] {title}")
        print(f"       Excerpt : {excerpt}")
        print(f"       URL     : {url}")
        print()
else:
    print("  No results returned (rate-limited or API failed — check stderr above)\n")

# ── TEST 3: Full assembled context block ─────────────────────────────────────
print(DIVIDER)
print("TEST 3 — Full context block injected into prompt")
print(DIVIDER)

ctx = fetch_external_context(title=SAMPLE_TITLE, category=SAMPLE_CATEGORY)

if ctx:
    print(ctx)
else:
    print("  Context is EMPTY — both sources returned nothing.")
    print("  The LLM will still run; the context block will be omitted from the prompt.")

print()
print(DIVIDER)
print("DONE")
print(DIVIDER)
