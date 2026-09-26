# Combined Spec — Unit 6 (QA Review Gate) + Unit 7 (Email Dispatch)

Scope: the final two components in the pipeline. Unit 6 is a read-only
approval gate over the Markdown produced by Unit 5 — no editing, just
Approve or Cancel. Unit 7 sends that exact Markdown via SMTP, triggered
only by Unit 6's approval. These are combined into one spec because Unit
7 fires as a direct consequence of Unit 6's "Approve & Send" click — they
share one button and one state transition, not two independent ones.

Builds on `st.session_state["final_markdown"]` from Unit 5 and `config.py`
from earlier units. Non-functional rule #4 from project.md — **"Gated
Delivery: email dispatch is never automatic upon Markdown generation"** —
is the entire reason these two units are combined: dispatch must be
provably reachable only through the approval click, never as a side
effect of rendering.

---

## 1. Preconditions

- Units 0–5 complete and passing their acceptance tests.
- `st.session_state["final_markdown"]` holds the string from Unit 5's
  `render_markdown`, non-empty.
- `.env` has the SMTP block and `DEFAULT_DEVELOPER_EMAIL` (already listed
  in the original `.env` structure). Add to `config.py` if not already
  present:

```python
# config.py — additions
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
DEFAULT_DEVELOPER_EMAIL = os.getenv("DEFAULT_DEVELOPER_EMAIL", "")
```

- No validation of these at import time (unlike `GROQ_API_KEY` in Unit
  2) — a missing SMTP credential is a legitimate first-run state before
  the tester has configured `.env`, and should surface as a send-time
  error in the UI, not crash the whole app on load.

---

## 2. State model — exact `st.session_state` keys this spec owns

| Key | Type | Set by | Meaning |
|---|---|---|---|
| `review_decision` | `"approved" \| "cancelled" \| None` | Unit 6 | The tester's choice on the currently-displayed Markdown. `None` = not yet decided. |
| `send_result` | `dict \| None` | Unit 7 | The dict returned by `send_report`, once a send has been attempted. `None` = not yet attempted. |
| `developer_email_input` | `str` | UI text input (Streamlit manages this key automatically via the widget's `key=`) | The tester-edited recipient address, prefilled from `config.DEFAULT_DEVELOPER_EMAIL`. |

These three keys are new in this unit — no earlier unit reads or writes
them. `final_markdown` and `report` (Units 4/5) are read here but never
written.

---

## 3. File: `pipeline/review.py`

### 3.1 Function contract

```python
def review_and_approve(decision: str) -> bool:
    """
    Args:
        decision: exactly "approve" or "cancel" — the tester's button
                   click, passed in by app.py. This function does not
                   render UI itself (Streamlit buttons live in app.py,
                   per the pattern established in every prior unit) — it
                   is the pure decision-recording step, called once per
                   click.

    Returns:
        True if decision == "approve", False if decision == "cancel".

    Raises:
        ValueError: if decision is anything other than "approve" or
            "cancel" — a caller bug, since app.py only ever passes one of
            these two literals.
    """
```

```python
def review_and_approve(decision: str) -> bool:
    if decision == "approve":
        return True
    elif decision == "cancel":
        return False
    else:
        raise ValueError(f'review_and_approve received invalid decision: "{decision}"')
```

### 3.2 Why this function is this thin

The spec's original signature was `review_and_approve(markdown: str) ->
bool`, implying it both displays the Markdown and blocks for input. That
doesn't map onto Streamlit's rerun-on-click model — there is no blocking
"wait for click" call available. The actual display already happened in
Unit 5 (`st.markdown(st.session_state["final_markdown"])`); this
function's real job is just: **given that a button was clicked, record
which one.** All UI — the two buttons, the state transition, the trigger
into Unit 7 — lives in `app.py` (Section 5), matching the pattern already
established for every previous unit's Streamlit-vs-pipeline split.

---

## 4. File: `pipeline/email_dispatch.py`

### 4.1 Function contract

```python
def send_report(markdown: str, developer_email: str) -> dict:
    """
    Args:
        markdown: the exact string to send as the email body — must be
                   st.session_state["final_markdown"], unmodified,
                   verbatim. No re-formatting, no HTML conversion, no
                   truncation.
        developer_email: recipient address, already validated as
                   non-empty by the caller (app.py) before this is called.

    Returns:
        {"status": "sent"} on success.
        {"status": "failed", "error": "<human-readable message>"} on any
        failure — SMTP connection error, auth failure, invalid recipient,
        etc. This function NEVER raises — every failure path is caught
        internally and returned as a "failed" dict, since the caller
        (app.py) needs a result to show a toast either way, not an
        exception to catch.
    """
```

### 4.2 Implementation

```python
import smtplib
from email.mime.text import MIMEText
import config


def send_report(markdown: str, developer_email: str) -> dict:
    if not config.SMTP_HOST or not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        return {
            "status": "failed",
            "error": "SMTP is not configured. Check SMTP_HOST, SMTP_USERNAME, "
                     "and SMTP_PASSWORD in .env.",
        }

    msg = MIMEText(markdown, "plain", "utf-8")
    msg["Subject"] = "Defect Report — Auto-Generated"
    msg["From"] = config.SMTP_FROM_EMAIL or config.SMTP_USERNAME
    msg["To"] = developer_email

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            if config.SMTP_USE_TLS:
                server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.sendmail(msg["From"], [developer_email], msg.as_string())
        return {"status": "sent"}
    except smtplib.SMTPAuthenticationError as e:
        return {"status": "failed", "error": f"SMTP authentication failed: {e}"}
    except smtplib.SMTPException as e:
        return {"status": "failed", "error": f"SMTP error: {e}"}
    except (OSError, TimeoutError) as e:
        return {"status": "failed", "error": f"Could not connect to SMTP server: {e}"}
    except Exception as e:
        return {"status": "failed", "error": f"Unexpected error sending email: {e}"}
```

### 4.3 Non-negotiable invariants

1. **The email body is the Markdown string verbatim.** Sent as
   `MIMEText(markdown, "plain", ...)` — plain text, not HTML-rendered —
   so what the developer receives is byte-identical to what the tester
   approved in the UI. This is what the acceptance test in Section 6
   checks directly.
2. **This function never raises.** Every exception type from `smtplib`
   and the socket layer is caught and converted to `{"status": "failed",
   "error": ...}`. `app.py` has exactly one shape to handle, not a
   try/except around a pipeline call.
3. **No retry loop.** One send attempt per call. A failed send requires
   the tester to click "Approve & Send" again (Section 5 handles this by
   not permanently disabling the button on failure).
4. **`developer_email` is passed in, not read from `config` directly** —
   `config.DEFAULT_DEVELOPER_EMAIL` is only ever used as the *prefill* for
   the UI text input (Section 5), never as a silent fallback inside this
   function. If the tester clears the field, dispatch must not
   fall back to sending elsewhere without their knowledge.

---

## 5. File: `app.py` — additions for this unit

Append directly after the Unit 5 "Markdown Preview" block. Do not remove
or restructure prior blocks.

```python
from pipeline.review import review_and_approve
from pipeline.email_dispatch import send_report
import config

st.divider()
st.subheader("QA Review")

final_markdown = st.session_state.get("final_markdown")

if final_markdown is None:
    st.info("Generate the Markdown preview first.")
else:
    review_decision = st.session_state.get("review_decision")

    if review_decision is None:
        developer_email = st.text_input(
            "Developer email",
            value=config.DEFAULT_DEVELOPER_EMAIL,
            key="developer_email_input",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Approve & Send", type="primary"):
                if not developer_email or not developer_email.strip():
                    st.warning("Enter a developer email before sending.")
                else:
                    st.session_state["review_decision"] = review_and_approve("approve")
                    with st.spinner("Sending email..."):
                        result = send_report(final_markdown, developer_email.strip())
                    st.session_state["send_result"] = result
                    st.rerun()
        with col2:
            if st.button("Cancel"):
                st.session_state["review_decision"] = review_and_approve("cancel")
                st.rerun()

    elif review_decision is False:
        st.warning("Report cancelled. No email was sent.")
        if st.button("Start New Report"):
            for key in ("report", "final_markdown", "review_decision", "send_result"):
                st.session_state.pop(key, None)
            st.rerun()

    elif review_decision is True:
        result = st.session_state.get("send_result")
        if result is None:
            st.error("Approved, but no send was attempted — this shouldn't happen.")
        elif result["status"] == "sent":
            st.success(f"✅ Report sent to {st.session_state.get('developer_email_input', '')}.")
        else:
            st.error(f"❌ Send failed: {result['error']}")
            if st.button("Retry Send"):
                with st.spinner("Retrying..."):
                    retry_result = send_report(
                        final_markdown,
                        st.session_state.get("developer_email_input", "").strip(),
                    )
                st.session_state["send_result"] = retry_result
                st.rerun()

        if st.button("Start New Report", key="start_new_after_send"):
            for key in ("report", "final_markdown", "review_decision", "send_result"):
                st.session_state.pop(key, None)
            st.rerun()
```

### 5.1 Notes

- **`review_and_approve` is called, then the send happens in the same
  click handler, synchronously, before `st.rerun()`.** This is what
  "Triggered immediately upon QA confirmation" (project.md, Component 7)
  means in a Streamlit rerun model — there is no separate deferred step;
  clicking "Approve & Send" and the SMTP call happen in one script pass.
- **"Cancel" never calls `send_report` at all** — not even with a
  short-circuit — `send_report` is textually unreachable from the Cancel
  branch. This is the literal enforcement of "Clicking Cancel halts the
  pipeline (no send)" from the acceptance criteria.
- Buttons are hidden once `review_decision` is set (not just disabled) —
  once approved or cancelled, the tester sees a result screen, not the
  same two buttons still sitting there inviting a second click.
- A failed send offers **"Retry Send"** rather than forcing the tester
  back through re-approval — the decision to approve was already made;
  only the SMTP attempt failed, so only that step retries.
- **"Start New Report"** clears exactly the four keys this and Unit 5 own
  (`report`, `final_markdown`, `review_decision`, `send_result`) — not
  `developer_email_input`, so the tester's last-used email address
  persists across reports in the same browser session (a minor
  convenience, not a requirement — remove that line if you'd rather reset
  it too).
- `type="primary"` on the Approve button is a Streamlit visual hint only,
  not a functional requirement — omit it if your Streamlit version/theme
  doesn't support the `type` kwarg.

---

## 6. Acceptance test (manual, browser)

Continue from a completed Unit 2→3→4→5 session using category **API**,
with `st.session_state["final_markdown"]` populated. Use a real inbox or
Mailtrap for the SMTP target per the original test note.

1. Confirm the "QA Review" section shows a developer-email text input
   prefilled with `DEFAULT_DEVELOPER_EMAIL` from `.env`, and two buttons:
   "Approve & Send" and "Cancel".
2. **Cancel path:** click "Cancel". Confirm:
   - A warning "Report cancelled. No email was sent." appears.
   - No spinner ever showed, no "sent"/"failed" toast ever appeared.
   - `st.session_state["send_result"]` is `None` (add a temporary
     `st.write(st.session_state)` if you need to inspect this directly).
3. Click "Start New Report" from the cancelled state. Confirm the app
   resets back to the category dropdown / text-area stage with no
   leftover Markdown or report visible.
4. Re-run the full pipeline to a fresh Markdown preview. This time clear
   the developer-email field entirely and click "Approve & Send" →
   confirm `st.warning("Enter a developer email before sending.")` fires
   and no send is attempted (check your test inbox receives nothing).
5. Re-enter a valid test-inbox address, click "Approve & Send" again.
   Confirm a spinner shows briefly, then a green
   `st.success("✅ Report sent to ...")` message appears.
6. Open the test inbox. Confirm:
   - The email arrives with subject "Defect Report — Auto-Generated".
   - The email body, character for character, matches
     `st.session_state["final_markdown"]` — copy the rendered Markdown
     from the UI (or add a temporary `st.code(final_markdown)` to grab
     the raw string) and diff it against the received email body. They
     must be identical — same field order, same `(AI annotated)` markers,
     same Developer Notes section.
7. **Failure path:** temporarily set `SMTP_PASSWORD=wrong_password_test`
   in `.env`, restart the app, run the pipeline to approval, click
   "Approve & Send" → confirm `st.error("❌ Send failed: SMTP
   authentication failed: ...")` appears, and a "Retry Send" button is
   offered. Restore the real password, click "Retry Send" → confirm it
   now succeeds without needing to re-approve or re-click "Approve & Send".
8. With a successful send showing, click "Start New Report". Confirm the
   app resets to the category/text-area stage again, and the developer
   email field (if you check it) still shows the last address you typed
   in step 5, not the `.env` default (per the deliberate choice in 5.1 —
   treat this as informational, not a failure, if you decided to reset it
   instead).

Once all 8 checks pass, Unit 6 + Unit 7 are complete. This is the final
unit in the build — Unit 8 (Full Pipeline Wiring) is only a consistency
pass over the `app.py` assembled incrementally across Units 0–7, not new
functionality.