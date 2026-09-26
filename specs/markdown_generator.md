# Spec — Unit 5 (Markdown Generator)

Scope: pure formatting — no Groq call, no network access. Takes the fully
reasoned report object produced by Unit 4 and renders it into a single
Markdown string for display. This is the first unit with zero LLM
involvement; every requirement below is deterministic string assembly.

Builds on `models/schemas.py` (`ReportObject`, `FieldObject`,
`DeveloperNotes`) and `app.py` from Units 0–4. Carries forward the same two
standing schema decisions:

- **No `optional_fields`.** Not read, not rendered, not referenced anywhere
  in this unit, despite the original project.md's example report.
- **Flat `fields` dict.** `render_markdown` iterates `report["fields"]`
  directly — no `core_fields`/`category_fields` split anywhere in the
  output.

---

## 1. Preconditions

- Units 0–4 complete and passing their acceptance tests.
- `st.session_state["report"]` holds a dict matching `ReportObject` with
  `developer_notes` populated (i.e. `reason_and_annotate` has run
  successfully — `report.get("developer_notes") is not None`).
- Every entry in `report["fields"]` has `source` in
  `{"tester_provided", "ai_annotated", "missing"}` — this unit renders all
  three states; it does not assume `missing` has been eliminated.

---

## 2. Field ordering — exact rule, not left to dict iteration order

`report["fields"]` is a Python dict, and dict key order in this codebase
has consistently been insertion order = the order `required_fields`
appeared in the resolved template (Unit 1's `resolve_template`, preserved
through Unit 2's `extract_fields`, Unit 3's clarification merge, and Unit
4's `reason_and_annotate`, which always rebuilds `new_fields` starting
from `copy.deepcopy(original_fields)`).

**`render_markdown` renders fields in `report["fields"].items()` order,
with no re-sorting, alphabetizing, or grouping.** Do not attempt to
recover "core vs category" grouping — that distinction no longer exists in
the data (see the standing schema decision above), and re-deriving it here
would require re-loading the template, which this function must not do
(pure formatting only, no I/O of any kind, `templates/` included).

---

## 3. File: `pipeline/markdown_generator.py`

### 3.1 Function contract

```python
def render_markdown(report: dict) -> str:
    """
    Args:
        report: dict matching ReportObject — {"category": str,
                "fields": {field_name: {"value": str|None, "source": str}},
                "developer_notes": {"description": str, "common_fixes": list[str]}}.
                developer_notes must not be None (see Preconditions).

    Returns:
        A single Markdown string. Pure function — same input always
        produces the same output. No LLM call, no file I/O, no network
        access, no side effects.

    Raises:
        MarkdownGenerationError: only for structurally invalid input —
            report["fields"] missing/not a dict, or
            report["developer_notes"] is None or missing. This is a
            caller-contract violation (should never happen if Unit 4's
            output feeds this directly), not a data-quality issue — there
            is no "recover and render partial output" path.
    """
```

Define in this file:

```python
class MarkdownGenerationError(Exception):
    pass
```

### 3.2 Field label formatting

Field names are `snake_case` internally (`steps_to_reproduce`,
`http_method`) but must render as human-readable labels
(`Steps To Reproduce`, `Http Method`).

```python
def _format_label(field_name: str) -> str:
    """
    snake_case -> Title Case With Spaces.
    "http_method" -> "Http Method"
    "steps_to_reproduce" -> "Steps To Reproduce"

    Deliberately NOT special-casing acronyms (no "HTTP Method",
    no "API endpoint") — a fixed acronym-exception list is a source of
    silent drift as fields are added later. Plain Title Case only.
    """
    return field_name.replace("_", " ").title()
```

This is a hard requirement: do not add an acronym dictionary, do not
special-case `http`/`api`/etc. Keep the transform mechanical and
predictable.

### 3.3 Per-field rendering rule

Each field renders as one Markdown line: a bolded label, a colon, then the
value (or a placeholder for `missing`), with the `ai_annotated` marker
appended only when applicable.

```python
def _render_field_line(field_name: str, field: dict) -> str:
    label = _format_label(field_name)
    source = field["source"]
    value = field["value"]

    if source == "missing":
        return f"**{label}:** _Not provided_"
    elif source == "tester_provided":
        return f"**{label}:** {value}"
    elif source == "ai_annotated":
        return f"**{label}:** {value} _(AI annotated)_"
    else:
        raise MarkdownGenerationError(
            f'Field "{field_name}" has unrecognized source "{source}".'
        )
```

Exact strings, not paraphrased at implementation time:
- `missing` → `_Not provided_` (italicized, not "N/A", not "Unknown" — the
  original tester_provided/ai_annotated/missing tri-state must stay
  visually distinguishable from an AI-declined-to-guess field elsewhere).
- `ai_annotated` marker is exactly `_(AI annotated)_` (italicized,
  parenthesized, one space before it), appended after the value, on the
  same line — never on its own line, never as a separate column.
- `tester_provided` gets **no** marker of any kind — this is the whole
  point of the visual distinction the acceptance test checks for.

### 3.4 Document structure — exact section order

```python
def render_markdown(report: dict) -> str:
    if "fields" not in report or not isinstance(report["fields"], dict):
        raise MarkdownGenerationError('report["fields"] is missing or not a dict.')

    dev_notes = report.get("developer_notes")
    if dev_notes is None:
        raise MarkdownGenerationError(
            "developer_notes is None — render_markdown requires a report "
            "that has already been through LLM #2 reasoning."
        )

    lines = []

    # 1. Title header
    category_display = report["category"].upper()
    lines.append(f"# Defect Report — {category_display}")
    lines.append("")

    # 2. Field section — one line per field, in report["fields"] order.
    for field_name, field in report["fields"].items():
        lines.append(_render_field_line(field_name, field))
    lines.append("")

    # 3. Developer notes section — always last, always present as a
    #    heading even if common_fixes is an empty list.
    lines.append("## Developer Notes")
    lines.append("")
    lines.append(dev_notes["description"])
    lines.append("")

    common_fixes = dev_notes.get("common_fixes", [])
    if common_fixes:
        lines.append("**Common Fixes:**")
        for fix in common_fixes:
            lines.append(f"- {fix}")
    else:
        lines.append("**Common Fixes:** _None suggested_")

    return "\n".join(lines)
```

### 3.5 Non-negotiable invariants (re-stated so they aren't lost in prose)

1. **No LLM call, no file I/O, no network access.** This function must be
   callable with a plain dict literal in a unit test with zero external
   dependencies — a violation of this (e.g. re-reading
   `templates/core_template.json` to recover field grouping) is a spec
   violation regardless of how it improves the output.
2. **Field order is exactly `report["fields"].items()` order** — no
   sorting, no core/category regrouping, no alphabetizing.
3. **`tester_provided` fields never carry any visual marker.** This is the
   single most important visual distinction in the whole document and the
   main thing the acceptance test checks — if a marker leaks onto a
   `tester_provided` field, that's the one bug this unit exists to prevent.
4. **`ai_annotated` marker text is exactly `_(AI annotated)_`, on the same
   line as the value.** Do not use a badge, an emoji, a separate line, or
   different wording.
5. **`missing` fields still render a line** — they are not skipped or
   omitted from the document. `_Not provided_` is the fixed placeholder.
6. **Developer Notes is always the last section**, always present with
   its heading, even when `common_fixes` is empty (rendered as `_None
   suggested_`, not an empty bullet list, not an omitted section).
7. Pure function: calling `render_markdown` twice on the identical input
   dict produces byte-identical output both times.

---

## 4. File: `app.py` — additions for this unit

Append directly after the Unit 4 "AI Reasoning" block (the before/after
JSON panels). Do not remove or restructure prior blocks.

```python
from pipeline.markdown_generator import render_markdown, MarkdownGenerationError

st.divider()
st.subheader("Markdown Preview")

report_in_state = st.session_state.get("report")

if report_in_state is None or report_in_state.get("developer_notes") is None:
    st.info("Run AI reasoning first to generate the Markdown preview.")
else:
    try:
        final_markdown = render_markdown(report_in_state)
        st.session_state["final_markdown"] = final_markdown
    except MarkdownGenerationError as e:
        st.error(f"Markdown generation failed: {e}")
        st.session_state.pop("final_markdown", None)

    if "final_markdown" in st.session_state:
        st.markdown(st.session_state["final_markdown"])
```

### 4.1 Notes

- `render_markdown` is called on **every rerun** once `developer_notes` is
  populated — unlike Units 2/4's explicit "Extract" / "Run AI Reasoning"
  buttons, there is no button here. This is intentional: the function is
  pure, cheap, and has no external call to guard against re-triggering, so
  gating it behind a button would only add friction with no benefit.
- `st.session_state["final_markdown"]` is stored (not just rendered
  inline) because Unit 6 (QA Review) and Unit 7 (Email Dispatch) both need
  the exact same string the tester is looking at — storing it here avoids
  re-deriving or re-calling `render_markdown` in those later units.
- `st.markdown(...)` renders the string as actual formatted Markdown in
  the browser (bold labels, italic markers, bullet list) — this is the
  "visually confirm" step the acceptance test relies on. Do not use
  `st.code` or `st.text` here, which would show raw Markdown syntax
  instead of the rendered result.

---

## 5. Acceptance test (manual, browser)

Continue from a completed Unit 2 → 3 → 4 session using category **API**
with the sample text from the Unit 2 spec (`title`, `endpoint`,
`http_method`, `status_code`, `expected_result`, `actual_result`,
`frequency` as `tester_provided`; `severity`, `priority`, `environment`
resolved by Units 3/4 to either `ai_annotated` or still `missing`).

1. Immediately after Unit 4's "Run AI Reasoning" completes, confirm the
   "Markdown Preview" section renders without needing any extra click.
2. Visually confirm the document opens with `# Defect Report — API` as the
   top-level heading.
3. For every field that was `tester_provided` (e.g. `title`, `endpoint`,
   `http_method`) — confirm the rendered line shows **bold label: value**
   with **no** `(AI annotated)` text anywhere on that line, and no other
   marker of any kind.
4. For every field that ended as `ai_annotated` (e.g. `severity` if the
   model inferred it) — confirm the rendered line shows **bold label:
   value _(AI annotated)_** in italics, on the same line as the value.
5. For any field still `missing` — confirm the rendered line shows **bold
   label: _Not provided_**.
6. Confirm field labels are readable Title Case (`Http Method`, `Steps To
   Reproduce`, `Status Code`) — acronym-looking fields are plain title
   case (`Http`, not `HTTP`) per the deliberate no-acronym-dictionary rule;
   this is expected, not a bug.
7. Confirm a `## Developer Notes` heading appears as the **last** section,
   with the `description` text below it, followed by either a bulleted
   `**Common Fixes:**` list or `**Common Fixes:** _None suggested_` if the
   model returned an empty list in Unit 4.
8. Confirm field order in the rendered document matches the order fields
   appeared in Unit 1's resolved template for API (9 core fields, then 5
   API fields) — no fields reordered, grouped, or alphabetized.
9. Re-run "Run AI Reasoning" is blocked by Unit 4's own guard (already
   verified in Unit 4's acceptance test) — confirm the Markdown preview
   here is unaffected and still shows the same content without needing any
   interaction, since it re-renders automatically from
   `st.session_state["report"]` on every rerun.
10. Select category "Other", run through Units 2→3→4 to get a reasoned
    report with only the 9 core fields, confirm the Markdown preview shows
    `# Defect Report — OTHER`, exactly 9 field lines, and no stray
    references to `endpoint`/`http_method`/etc.

Once all 10 checks pass, Unit 5 is complete and Unit 6 (QA Review Gate)
can consume `st.session_state["final_markdown"]` as-is, unmodified.