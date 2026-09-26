# Technical Specification — Unit 3: Clarification Loop

## 1. Overview & Components

* **Target File**: `pipeline/clarification.py`

* **Target Function**: `extract_clarifications(missing_fields: list[str], user_input_text: str) -> dict[str, str]`

* **Primary Objective**: Re-prompt the QA tester to collect natural language input for missing fields, perform a targeted LLM extraction, update field statuses, and permanently lock unaddressed or explicitly skipped fields from further prompting during the session.



---

## 2. Component Contracts & Responsibilities

### Target Function

```python
def extract_clarifications(
    missing_fields: list[str], 
    user_input_text: str
) -> dict[str, str]:
    """Targeted LLM #1 call.
    Parses freeform natural language text supplied by the QA tester 
    specifically for keys in missing_fields.
    
    Args:
        missing_fields: List of field names currently tagged as missing and unlocked.
        user_input_text: Natural language response supplied by the QA tester.

    Returns:
        dict[str, str]: Dictionary mapping field names to extracted string values.
    """
```[cite: 2]

---

## 3. UI Requirements & State Management

* **UI Display**: Renders a list of remaining unlocked missing fields, along with a single combined text area (`st.text_area`) with the label "Describe anything you know about the missing fields"[cite: 2].
* **Action Trigger**: Includes a "Submit clarification" button[cite: 2].
* **Dynamic Re-rendering**: Updates the list of displayed missing fields upon submission, re-rendering only those fields that remain missing and unlocked[cite: 2].
* **Session State Tracking**: Tracks locked fields in `st.session_state` to guarantee that once a field is locked, it is never re-prompted in the current session[cite: 2].

---

## 4. LLM & Extraction Logic

* **Execution**: Performs a targeted LLM #1 call scoped strictly to the list of `missing_fields` passed into `extract_clarifications()`[cite: 2].
* **Value Processing**:
  * Extracted non-null string values update the corresponding field in the report object with `source: "tester_provided"`[cite: 2].
  * If the input is explicit ("unknown", "skip", "pass", "don't know") or yields no match for a key in `missing_fields`, the field value remains `null` with `source: "missing"`[cite: 2].

---

## 5. Field Lifecycle & Locking Rules

* **Permanence**: Any field unaddressed by the tester or explicitly marked as unknown/skipped transitions to a permanently locked state in `st.session_state`[cite: 2].
* **Pipeline Transition**: Once all missing fields are either filled (`tester_provided`) or locked (`missing`), the clarification loop terminates and passes the report directly to LLM #2 for reasoning[cite: 2].

---

## 6. Manual Verification & Test Plan

| Test Step | Action | Expected Outcome |
| :--- | :--- | :--- |
| **1. Partial Clarification** | For 3 missing fields, submit input addressing only 2 fields[cite: 2]. | The 2 addressed fields update to `source: "tester_provided"`; the 1 unaddressed field remains `missing`[cite: 2]. |
| **2. Field Locking Check** | Enter "skip" or leave the final remaining field unaddressed[cite: 2]. | The field remains `source: "missing"`, locks in `st.session_state`, and is removed from UI prompts[cite: 2]. |
| **3. Loop Exit Verification** | Confirm UI state when zero unlocked missing fields remain[cite: 2]. | The clarification UI hides and the pipeline advances to LLM #2 (`reason_and_annotate`)[cite: 2]. |

```