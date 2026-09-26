# Spec — Unit 4 (LLM #2 Reasoning)

Scope: given the report object produced by Unit 2 (and refined by Unit 3's
clarification loop, if built), run one Groq call that fills any remaining
`missing` fields as `ai_annotated` and writes `developer_notes`. Enforces
in code — not by trusting the prompt — that no `tester_provided` field is
ever altered.

Builds on `models/schemas.py`, `pipeline/llm_extraction.py`, `app.py`, and
`utils/groq_client.py` / `utils/json_utils.py` from Units 0–2. Two schema
decisions from earlier units carry forward unchanged and are restated here
so this spec is self-contained:

- **No `optional_fields`.** They were removed in the Unit 0/1 rewrite.
  This spec does **not** reintroduce them, even though the original
  project.md mentions them. `reason_and_annotate` only ever touches the
  single flat `fields` dict plus the new `developer_notes` key below.
- **Flat `fields` dict**, not `core_fields`/`category_fields` split — as
  decided in Unit 2. `reason_and_annotate` operates on that same flat
  dict.

---

## 1. Preconditions

- Unit 0, 1, 2 complete and passing their acceptance tests.
- `st.session_state["report"]` holds a dict matching `ReportObject` from
  Unit 2 (`category`, `fields`), possibly updated by a Unit 3 clarification
  loop so that every field is now either `tester_provided` or a
  **permanently locked** `missing`.
- If Unit 3 has not been built yet: this unit still works standalone —
  "locked" simply means "still `missing` after Unit 2's extraction", since
  there's no clarification step to have changed that. The UI gating in
  Section 5 accounts for both cases.
- `.env` / `config.py` already has `GROQ_MODEL_EXTRACTION`. Add a second,
  independent model var so LLM #2 can be swapped separately from LLM #1
  later without code changes:

```python
# config.py — addition
GROQ_MODEL_REASONING = os.getenv("GROQ_MODEL_REASONING", "llama-3.3-70b-versatile")
```

(This matches the `.env` structure from the original spec, which already
lists `GROQ_MODEL_REASONING` separately from `GROQ_MODEL_EXTRACTION`.)

---

## 2. Schema change: `models/schemas.py`

Add `developer_notes` to `ReportObject`. This is the **first** unit that
populates it — Unit 2's output has no `developer_notes` key at all; Unit 4
adds it.

```python
class DeveloperNotes(BaseModel):
    description: str
    common_fixes: list[str]

class ReportObject(BaseModel):
    category: str
    fields: dict[str, FieldObject]
    developer_notes: DeveloperNotes | None = None
    # None until Unit 4 runs; Unit 2's output always has this as None
    # (or the key omitted, per .model_dump(exclude_none=True) — see 2.1).
```

### 2.1 Compatibility with Unit 2's output

Unit 2's `extract_fields` builds `ReportObject(category=..., fields=...)`
without passing `developer_notes` — with the `| None = None` default this
still validates cleanly; no change needed to `llm_extraction.py`. The
`.model_dump()` call in `extract_fields` will now include a
`"developer_notes": null` key. That's acceptable and expected — Unit 4
looks for `report.get("developer_notes") is None` to decide whether
reasoning has already run (see Section 3.4, idempotency note).

---

## 3. File: `pipeline/llm_reasoning.py`

### 3.1 Function contract

```python
def reason_and_annotate(report: dict) -> dict:
    """
    Args:
        report: dict matching ReportObject, as currently held in
                st.session_state["report"]. Every entry in report["fields"]
                must have source in {"tester_provided", "missing"} —
                if any field already has source == "ai_annotated", that is
                a caller bug (this function being called twice) and is
                rejected (see 3.5, rule 4).

    Returns:
        A new dict matching ReportObject.model_dump(), where:
        - every field that was "tester_provided" in the input is
          byte-identical (same "value" string, same "source") in the output.
        - every field that was "missing" in the input is EITHER still
          "missing"/None (LLM genuinely could not infer it) OR now
          "ai_annotated" with a non-null, non-empty value.
        - "developer_notes" is populated: {"description": str,
          "common_fixes": list[str]} (list may be empty if the model
          truly has nothing to suggest, but the key itself is always
          present).

    Raises:
        LLMReasoningError: wraps Groq API failure, malformed JSON,
            schema validation failure, or — critically — a detected
            mutation of a tester_provided field (see 3.5, rule 3). This
            last case aborts and returns nothing; the caller's existing
            st.session_state["report"] is left untouched.
    """
```

Define in this file:

```python
class LLMReasoningError(Exception):
    pass
```

### 3.2 Prompt — exact structure (file: `prompts/reasoning_prompt.py`)

```python
def build_reasoning_messages(report: dict) -> list[dict]:
    fields = report["fields"]

    tester_provided = {
        k: v["value"] for k, v in fields.items() if v["source"] == "tester_provided"
    }
    missing = [k for k, v in fields.items() if v["source"] == "missing"]

    system_prompt = (
        "You are a defect-report reasoning assistant. You are given a "
        "partially-filled bug report: some fields are already confirmed by "
        "a human tester, and some fields are missing. Your job is to: "
        "(1) infer values for missing fields ONLY where the confirmed "
        "fields make a reasonable inference possible, and (2) write a "
        "short developer-facing summary and a list of common fixes. "
        "You must NEVER invent a change to, or restate a modified version "
        "of, any field that is already confirmed — those are provided "
        "verbatim below for context only, not for you to edit. "
        "You respond with ONLY a single JSON object — no markdown code "
        "fences, no preamble, no explanation."
    )

    user_prompt = (
        f"Bug category: {report['category']}\n\n"
        f"Confirmed fields (context only — do NOT include these in your "
        f"output, they are already final):\n"
        f"{json.dumps(tester_provided, indent=2)}\n\n"
        f"Fields still missing (infer a value ONLY if the confirmed "
        f"fields above genuinely support a specific inference; otherwise "
        f'leave as null — do not guess vague filler like "unknown" or '
        f'"N/A"):\n'
        f"{json.dumps(missing)}\n\n"
        f"Return a JSON object with exactly this shape:\n"
        f'{{\n'
        f'  "annotated_fields": {{"<field_name>": "<inferred value or null>"}},\n'
        f'  "developer_notes": {{\n'
        f'    "description": "<2-4 sentence summary for the developer>",\n'
        f'    "common_fixes": ["<short suggestion>", "..."]\n'
        f'  }}\n'
        f'}}\n\n'
        f"Rules:\n"
        f'1. "annotated_fields" must contain exactly the keys listed in '
        f'"Fields still missing" above — no more, no fewer, and none of '
        f"the confirmed field names.\n"
        f'2. Set a field\'s value to null in "annotated_fields" if you '
        f"cannot make a genuine, specific inference — an empty guess is "
        f"worse than admitting you don't know.\n"
        f'3. "common_fixes" may be an empty list if nothing applies, but '
        f"the key must be present.\n"
        f"4. Output ONLY the JSON object. No other text."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
```

Note the prompt design deliberately **excludes** the confirmed fields from
the field-list the model is asked to output (`annotated_fields` only
covers `missing` keys) — this makes "the model restated a tester_provided
field" structurally harder, on top of the code-level diff check in 3.5,
which is the actual enforcement mechanism and must not be skipped just
because the prompt makes it less likely.

### 3.3 Reuse from Unit 2

- `utils/groq_client.py`'s `chat_completion(messages, model)` — call with
  `model=config.GROQ_MODEL_REASONING`.
- `utils/json_utils.py`'s `extract_json_object(raw)` — same fence-stripping
  parse.
- No new low-level utility files needed for this unit besides the diff
  checker in Section 4.

### 3.4 `reason_and_annotate` implementation requirements — step by step

```python
import copy
import json
from pydantic import ValidationError

from models.schemas import ReportObject, FieldObject, DeveloperNotes
from utils.groq_client import chat_completion
from utils.json_utils import extract_json_object
from utils.diff_check import assert_tester_provided_unchanged
from prompts.reasoning_prompt import build_reasoning_messages
import config


class LLMReasoningError(Exception):
    pass


def reason_and_annotate(report: dict) -> dict:
    original_fields = copy.deepcopy(report["fields"])

    # Guard: reject if this report has already been through reasoning.
    # (Idempotency / caller-bug protection — see 3.5 rule 4.)
    if any(f["source"] == "ai_annotated" for f in original_fields.values()):
        raise LLMReasoningError(
            "reason_and_annotate called on a report that already has "
            "ai_annotated fields. Refusing to run twice on the same report."
        )

    missing_keys = [k for k, v in original_fields.items() if v["source"] == "missing"]

    messages = build_reasoning_messages(report)

    try:
        raw_response = chat_completion(messages, model=config.GROQ_MODEL_REASONING)
    except Exception as e:
        raise LLMReasoningError(f"Groq API call failed: {e}") from e

    try:
        parsed = extract_json_object(raw_response)
    except json.JSONDecodeError as e:
        raise LLMReasoningError(
            f"Model did not return valid JSON. Raw response:\n{raw_response}"
        ) from e

    if "annotated_fields" not in parsed or not isinstance(parsed["annotated_fields"], dict):
        raise LLMReasoningError(
            f'Model response missing "annotated_fields" object. Got: {parsed}'
        )
    if "developer_notes" not in parsed or not isinstance(parsed["developer_notes"], dict):
        raise LLMReasoningError(
            f'Model response missing "developer_notes" object. Got: {parsed}'
        )

    annotated = parsed["annotated_fields"]

    # --- Code-level checks (NOT delegated to the prompt/model) ---

    # 1. annotated_fields keys must be exactly the missing set. No extras,
    #    no touching a tester_provided field name, none dropped.
    got_keys = set(annotated.keys())
    expected_keys = set(missing_keys)
    if got_keys != expected_keys:
        raise LLMReasoningError(
            f"annotated_fields key mismatch. Expected exactly {sorted(expected_keys)}, "
            f"got {sorted(got_keys)}."
        )

    # 2. Build the new fields dict, starting from an untouched copy of the
    #    original so tester_provided entries are never re-derived from the
    #    model's output even accidentally.
    new_fields = copy.deepcopy(original_fields)

    for field_name in missing_keys:
        value = annotated[field_name]
        if value is None or (isinstance(value, str) and value.strip() == ""):
            # Model could not infer it — leave as missing, untouched.
            continue
        new_fields[field_name] = FieldObject(
            value=str(value).strip(),
            source="ai_annotated",
        ).model_dump()

    # 3. THE critical enforcement: diff-check tester_provided fields
    #    between original and new, byte-for-byte. This is what the spec's
    #    non-functional rule #2 actually requires — not a prompt promise.
    assert_tester_provided_unchanged(original_fields, new_fields)

    # 4. developer_notes validation via Pydantic.
    try:
        dev_notes = DeveloperNotes(
            description=parsed["developer_notes"].get("description", ""),
            common_fixes=parsed["developer_notes"].get("common_fixes", []),
        )
    except ValidationError as e:
        raise LLMReasoningError(f"developer_notes failed schema validation: {e}") from e

    if not dev_notes.description.strip():
        raise LLMReasoningError("developer_notes.description was empty.")

    # 5. Final full-report validation.
    try:
        result = ReportObject(
            category=report["category"],
            fields={k: FieldObject(**v) for k, v in new_fields.items()},
            developer_notes=dev_notes,
        )
    except ValidationError as e:
        raise LLMReasoningError(f"Final report object failed schema validation: {e}") from e

    return result.model_dump()
```

### 3.5 Non-negotiable invariants (re-stated so they aren't lost in prose)

1. `reason_and_annotate` never reads or writes any field whose `source`
   was `tester_provided` in the input, other than to carry it forward
   unmodified in `new_fields = copy.deepcopy(original_fields)`. The model
   is never even asked to output those field names (Section 3.2's prompt
   omits them from the requested `annotated_fields` keys).
2. Every `missing` field in the input ends the function as either still
   `missing`/`None`, or `ai_annotated` with a genuine, non-empty value.
   Never left in any other state, never forced to a placeholder like
   `"unknown"` or `"N/A"`.
3. **The diff check in step 3 (`assert_tester_provided_unchanged`) is the
   actual enforcement of non-functional rule #2** — "Immutability of
   Human Input" — not the prompt wording. If it fires, the whole call
   fails via `LLMReasoningError` and `st.session_state["report"]` is left
   as it was before the call (see Section 5 — the caller must not
   overwrite session state until `reason_and_annotate` returns
   successfully).
4. This function refuses to run on a report that already contains an
   `ai_annotated` field (guards against the tester double-clicking "Run AI
   Reasoning" and silently re-annotating on top of prior annotations,
   which would make the diff check meaningless on the second pass).
5. One Groq call per invocation. No retry loop in this unit.

---

## 4. File: `utils/diff_check.py`

```python
class TesterProvidedMutationError(Exception):
    pass


def assert_tester_provided_unchanged(original_fields: dict, new_fields: dict) -> None:
    """
    Raises TesterProvidedMutationError, naming every offending field, if
    any field that was source == "tester_provided" in original_fields has
    a different "value" or a different "source" in new_fields.

    This must be called with the ORIGINAL pre-LLM-#2 fields dict and the
    CANDIDATE post-LLM-#2 fields dict, both in the same
    {field_name: {"value": ..., "source": ...}} shape.
    """
    violations = []
    for field_name, original in original_fields.items():
        if original["source"] != "tester_provided":
            continue
        new = new_fields.get(field_name)
        if new is None:
            violations.append(f'{field_name}: dropped entirely')
            continue
        if new["source"] != "tester_provided" or new["value"] != original["value"]:
            violations.append(
                f'{field_name}: was {original!r}, became {new!r}'
            )

    if violations:
        raise TesterProvidedMutationError(
            "tester_provided fields were mutated by LLM #2 reasoning: "
            + "; ".join(violations)
        )
```

`pipeline/llm_reasoning.py` catches `TesterProvidedMutationError` nowhere
special — it's allowed to propagate up, but `reason_and_annotate` should
wrap it into `LLMReasoningError` at the call site so `app.py` only ever
needs to catch one exception type from this module:

```python
    try:
        assert_tester_provided_unchanged(original_fields, new_fields)
    except TesterProvidedMutationError as e:
        raise LLMReasoningError(str(e)) from e
```

(Fold this into step 3 of Section 3.4 rather than leaving it bare.)

---

## 5. File: `app.py` — additions for this unit

Append after the Unit 2 extraction block (and after Unit 3's clarification
loop block, if built). Do not remove or restructure prior blocks.

```python
from pipeline.llm_reasoning import reason_and_annotate, LLMReasoningError

st.divider()
st.subheader("AI Reasoning")

report_in_state = st.session_state.get("report")

if report_in_state is None:
    st.info("Extract a report first.")
else:
    fields = report_in_state["fields"]
    still_missing = [k for k, v in fields.items() if v["source"] == "missing"]
    already_reasoned = report_in_state.get("developer_notes") is not None

    if already_reasoned:
        st.info("AI reasoning has already run on this report.")
    else:
        # Gating: enabled once the clarification loop (Unit 3) is exhausted.
        # If Unit 3 is not yet built, "exhausted" is vacuously true right
        # after extraction, since there is no locking mechanism yet to wait on.
        clarification_pending = st.session_state.get("clarification_pending", False)

        run_disabled = clarification_pending
        if run_disabled:
            st.warning("Resolve or skip all clarification prompts before running AI reasoning.")

        if st.button("Run AI Reasoning", disabled=run_disabled):
            with st.spinner("Running AI reasoning..."):
                try:
                    before_snapshot = copy.deepcopy(report_in_state)
                    updated_report = reason_and_annotate(report_in_state)
                    st.session_state["report"] = updated_report
                    st.session_state["report_before_reasoning"] = before_snapshot
                except LLMReasoningError as e:
                    st.error(f"AI reasoning failed: {e}")

    if "report_before_reasoning" in st.session_state:
        st.markdown("**Before / After**")
        col1, col2 = st.columns(2)
        with col1:
            st.caption("Before")
            st.json(st.session_state["report_before_reasoning"])
        with col2:
            st.caption("After")
            st.json(st.session_state["report"])
```

Add `import copy` at the top of `app.py` alongside the existing imports.

### 5.1 Notes

- `clarification_pending` is a session-state flag this spec assumes Unit 3
  sets (`True` while unresolved missing fields still await a tester
  response, `False`/absent once every field is either filled or
  permanently locked as `missing`). If Unit 3 hasn't been built yet in
  your build order, this flag simply never gets set to `True`, so
  `run_disabled` is always `False` and the button is enabled right after
  extraction — matching "no gate to wait on" until Unit 3 exists.
- `already_reasoned` uses the same signal as the function-level guard in
  3.4 rule 4 (`developer_notes is not None`) so the UI and the function
  agree on what "already ran" means — don't invent a second flag for this.
- On failure, `st.session_state["report"]` is **not** touched — the
  `try` block only assigns to it after `reason_and_annotate` returns
  successfully, so a failed run leaves the prior state exactly as it was,
  matching invariant 3 in Section 3.5.
- The before/after panels use a **separate** session key
  (`report_before_reasoning`), not a re-derivation — this is the literal
  snapshot taken immediately before the call, so what's shown in "Before"
  is guaranteed to be what `reason_and_annotate` actually received.

---

## 6. Acceptance test (manual, browser)

Continue from a Unit 2 (or Unit 2+3) session using category **API** with
the sample text from the Unit 2 spec, so `severity`, `priority`, and
`environment` are `missing` and everything else is `tester_provided`.

1. With `severity`, `priority`, `environment` still `missing` (either
   skipped via a Unit 3 clarification loop, or straight from Unit 2 if
   Unit 3 isn't built yet), click **"Run AI Reasoning"**.
2. A spinner shows, then two side-by-side JSON panels render: "Before" and
   "After".
3. Diff the two panels by hand for every field that was `tester_provided`
   before (`title`, `endpoint`, `http_method`, `status_code`,
   `expected_result`, `actual_result`, `frequency`, etc. — whichever the
   sample text filled) — confirm `value` and `source` are **identical**,
   character for character, in both panels.
4. For `severity`, `priority`, `environment` — confirm each is now either:
   - `source: "ai_annotated"` with a plausible non-null value (e.g.
     `severity` inferred as "High" given a 500 error on every request), or
   - still `source: "missing"`, `value: null`, if the model declined to
     guess — either outcome is a pass, as long as it's one of these two,
     never a placeholder string.
5. Confirm `developer_notes.description` is a non-empty string and
   `developer_notes.common_fixes` is present as a list (empty list is
   acceptable, missing key is not).
6. Click **"Run AI Reasoning"** again (if the button/logic still allows
   it) → confirm `st.info("AI reasoning has already run on this report.")`
   fires instead of a second Groq call, and the report in state is
   unchanged from step 4/5.
7. Force a mutation to prove the guard works: temporarily edit
   `prompts/reasoning_prompt.py`'s user prompt to instead say "Also
   restate the confirmed fields with corrected values in
   annotated_fields" (a deliberately bad prompt), rerun steps 1–2 on a
   fresh extraction → confirm `st.error("AI reasoning failed: ...tester_provided
   fields were mutated...")` fires, and `st.session_state["report"]` still
   shows the **original** unmutated values (check the "report" JSON
   still reads as it did right after Unit 2's extraction, not a
   half-mutated version). Revert the prompt file afterward.
8. Select category "Other" (9 core fields only, no `endpoint` etc.),
   extract with a short text leaving several fields missing, run AI
   Reasoning → confirm it completes without error and doesn't reference
   any API-specific field names anywhere in its output.

Once all 8 checks pass, Unit 4 is complete and Unit 5 (Markdown Generator)
can consume `st.session_state["report"]`, including its now-populated
`developer_notes`, as-is.