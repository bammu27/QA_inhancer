import copy
import html
import streamlit as st
from pipeline.template_loader import resolve_template, list_categories
from pipeline.llm_extraction import extract_fields
from pipeline.clarification import (
    extract_clarifications,
    get_unlocked_missing_fields,
    apply_clarifications,
)
from pipeline.llm_reasoning import reason_and_annotate, LLMReasoningError
from pipeline.markdown_generator import render_markdown, MarkdownGenerationError
from pipeline.review import review_and_approve
from pipeline.email_dispatch import send_report
import config

st.set_page_config(
    page_title="Defect Description Enhancer",
    page_icon="🐞",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 880px; }
    h1 { font-weight: 700; }
    h3, h4 { font-weight: 600; }

    /* Stepper */
    .stepper { display: flex; align-items: center; margin: 0.5rem 0 2rem 0; }
    .step { display: flex; align-items: center; flex: 1; }
    .step:last-child { flex: 0; }
    .step-circle {
        width: 28px; height: 28px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 0.8rem; font-weight: 700; color: white; flex-shrink: 0;
    }
    .step-label { margin-left: 0.5rem; font-size: 0.82rem; white-space: nowrap; }
    .step-line { flex: 1; height: 2px; margin: 0 0.6rem; }

    /* Badges */
    .badge {
        display: inline-block; padding: 3px 12px; border-radius: 999px;
        font-size: 0.8rem; font-weight: 600; margin-right: 6px;
    }

    /* Cards */
    .card {
        border: 1px solid rgba(120,120,120,0.25); border-radius: 12px;
        padding: 1rem 1.2rem; margin-bottom: 0.9rem; background: rgba(120,120,120,0.04);
    }
    .card-title { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em;
        opacity: 0.65; margin-bottom: 0.3rem; }
    .card-value { font-size: 1rem; }

    .diff-row { border-radius: 10px; padding: 0.7rem 0.9rem; margin-bottom: 0.6rem;
        border: 1px solid rgba(120,120,120,0.2); }
    .diff-label { font-weight: 600; font-size: 0.88rem; margin-bottom: 0.3rem; }
    .diff-old { color: #b91c1c; }
    .diff-new { color: #15803d; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🐞 Defect Description Enhancer")
st.caption("Turn a raw bug dump into a clean, developer-ready report.")

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

STEPS = ["Extract", "Clarify", "Reason", "Preview", "Send"]

PRIORITY_COLORS = {
    "critical": "#dc2626", "high": "#ea580c", "medium": "#ca8a04",
    "low": "#16a34a", "": "#6b7280",
}
STATUS_COLORS = {
    "open": "#2563eb", "in progress": "#ca8a04", "resolved": "#16a34a",
    "closed": "#6b7280", "": "#6b7280",
}


def badge(text, color):
    return (
        f'<span class="badge" style="background:{color}22;color:{color};'
        f'border:1px solid {color}55;">{html.escape(str(text))}</span>'
    )


def format_label(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().title()


def current_step_index(report, unlocked_missing, final_markdown, review_decision, send_result):
    if report is None:
        return 0
    if unlocked_missing:
        return 1
    if report.get("developer_notes") is None:
        return 2
    if final_markdown is None:
        return 3
    if review_decision is True and send_result and send_result.get("status") == "sent":
        return 5
    return 4


def render_stepper(active_index):
    parts = ['<div class="stepper">']
    for i, label in enumerate(STEPS):
        if i < active_index:
            circle_color, text_color = "#16a34a", "#16a34a"
            content = "✓"
        elif i == active_index:
            circle_color, text_color = "#2563eb", "#2563eb"
            content = str(i + 1)
        else:
            circle_color, text_color = "#9ca3af", "#9ca3af"
            content = str(i + 1)
        parts.append('<div class="step">')
        parts.append(f'<div class="step-circle" style="background:{circle_color};">{content}</div>')
        parts.append(f'<div class="step-label" style="color:{text_color};">{html.escape(label)}</div>')
        if i < len(STEPS) - 1:
            line_color = "#16a34a" if i < active_index else "#d1d5db"
            parts.append(f'<div class="step-line" style="background:{line_color};"></div>')
        parts.append("</div>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_value(value):
    if value is None or value == "":
        st.markdown("*(empty)*")
    elif isinstance(value, list):
        if not value:
            st.markdown("*(empty list)*")
        else:
            st.markdown("\n".join(f"- {v}" for v in value))
    elif isinstance(value, dict):
        for k, v in value.items():
            st.markdown(f"**{format_label(k)}:** {v}")
    else:
        st.write(value)


def compute_diff(before: dict, after: dict):
    changes = []
    for key in sorted(set(before.keys()) | set(after.keys())):
        old_val, new_val = before.get(key), after.get(key)
        if old_val != new_val:
            changes.append((key, old_val, new_val))
    return changes


def render_diff(changes):
    if not changes:
        st.caption("AI reasoning ran but didn't change any fields.")
        return
    for key, old_val, new_val in changes:
        st.markdown(f'<div class="diff-row"><div class="diff-label">{html.escape(format_label(key))}</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Before")
            st.markdown(f'<div class="diff-old">', unsafe_allow_html=True)
            render_value(old_val)
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.caption("After")
            st.markdown(f'<div class="diff-new">', unsafe_allow_html=True)
            render_value(new_val)
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def render_report_dashboard(report: dict, fallback_category: str):
    category = report.get("category") or fallback_category
    priority = str(report.get("priority", "")).strip()
    status = str(report.get("status", "")).strip()

    badges_html = badge(category, "#2563eb")
    if priority:
        badges_html += badge(priority, PRIORITY_COLORS.get(priority.lower(), "#6b7280"))
    if status:
        badges_html += badge(status, STATUS_COLORS.get(status.lower(), "#6b7280"))
    st.markdown(badges_html, unsafe_allow_html=True)
    st.write("")

    long_text_keys = [
        "title", "summary", "description", "steps_to_reproduce",
        "expected_result", "actual_result", "environment", "developer_notes",
    ]
    handled = {"category", "priority", "status"}

    for key in long_text_keys:
        if key in report and report.get(key):
            handled.add(key)
            expanded = key in ("summary", "developer_notes", "description")
            with st.expander(f"📝 {format_label(key)}", expanded=expanded):
                render_value(report[key])

    simple_fields = {
        k: v for k, v in report.items()
        if k not in handled and not isinstance(v, (dict, list)) and v not in (None, "")
    }
    if simple_fields:
        st.markdown("#### Details")
        keys = list(simple_fields.keys())
        cols = st.columns(3)
        for i, k in enumerate(keys):
            with cols[i % 3]:
                st.markdown(
                    f'<div class="card"><div class="card-title">{html.escape(format_label(k))}</div>'
                    f'<div class="card-value">{html.escape(str(simple_fields[k]))}</div></div>',
                    unsafe_allow_html=True,
                )
        handled.update(keys)

    list_fields = {k: v for k, v in report.items() if isinstance(v, list) and v}
    for k, v in list_fields.items():
        handled.add(k)
        with st.expander(f"📋 {format_label(k)} ({len(v)})"):
            render_value(v)

    dict_fields = {k: v for k, v in report.items() if isinstance(v, dict) and v}
    for k, v in dict_fields.items():
        handled.add(k)
        with st.expander(f"🗂️ {format_label(k)}"):
            render_value(v)

    with st.expander("🔍 View raw data (debug)"):
        st.json(report)


# --------------------------------------------------------------------------
# Category + template selection
# --------------------------------------------------------------------------

categories = list_categories()  # always non-empty: "Other" is guaranteed

selected_category = st.selectbox("Bug category", categories)

try:
    template = resolve_template(selected_category.lower())
except ValueError as e:
    st.error(f"Template schema error: {e}")
    st.stop()

# --------------------------------------------------------------------------
# Stepper (computed before the extract step so it shows on first load too)
# --------------------------------------------------------------------------

_report_preview = st.session_state.get("report")
_unlocked_preview = (
    get_unlocked_missing_fields(_report_preview, st.session_state.get("locked_fields", set()))
    if _report_preview is not None else []
)
render_stepper(
    current_step_index(
        _report_preview,
        _unlocked_preview,
        st.session_state.get("final_markdown"),
        st.session_state.get("review_decision"),
        st.session_state.get("send_result"),
    )
)

# --------------------------------------------------------------------------
# Step 1 — Extract
# --------------------------------------------------------------------------

st.subheader("1 · Raw Defect Description")
raw_text = st.text_area(
    "Paste raw defect report text here:",
    height=180,
    placeholder="e.g. When performing POST /api/v1/checkout on Chrome/Win11, getting HTTP 500 Internal Server Error every time. Payload sent was {'cart_id': 123}. Expected 200 OK.",
)

if st.button("🚀 Extract", type="primary"):
    if not raw_text.strip():
        st.warning("Please enter raw defect text before clicking Extract.")
    else:
        with st.spinner("Extracting fields with Groq LLM..."):
            try:
                report = extract_fields(raw_text, template)
                st.session_state["report"] = report
                st.session_state["locked_fields"] = set()
                st.session_state.pop("report_before_reasoning", None)
                st.session_state.pop("final_markdown", None)
                st.session_state.pop("review_decision", None)
                st.session_state.pop("send_result", None)
                st.rerun()
            except Exception as e:
                st.error(f"Extraction error: {e}")

if "report" in st.session_state:
    report = st.session_state["report"]
    locked_fields = st.session_state.get("locked_fields", set())

    unlocked_missing = get_unlocked_missing_fields(report, locked_fields)

    st.divider()

    # ----------------------------------------------------------------
    # Step 2 — Clarify
    # ----------------------------------------------------------------
    if unlocked_missing:
        st.subheader("2 · Clarification Needed")
        formatted_missing = " ".join(badge(f, "#ea580c") for f in unlocked_missing)
        st.markdown(f"**{len(unlocked_missing)} required field(s) still missing:**", unsafe_allow_html=False)
        st.markdown(formatted_missing, unsafe_allow_html=True)
        st.write("")

        clarification_text = st.text_area(
            "Describe anything you know about the missing fields",
            height=110,
            placeholder="e.g. Priority is High. Environment OS is Windows 11.",
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("✅ Submit clarification", type="primary"):
                with st.spinner("Processing clarification..."):
                    try:
                        extracted = extract_clarifications(unlocked_missing, clarification_text)
                        report, locked_fields = apply_clarifications(
                            report, unlocked_missing, extracted, locked_fields
                        )
                        st.session_state["report"] = report
                        st.session_state["locked_fields"] = locked_fields
                        st.rerun()
                    except Exception as e:
                        st.error(f"Clarification processing error: {e}")
        with col2:
            if st.button("⏭️ Skip remaining fields"):
                for field in unlocked_missing:
                    locked_fields.add(field)
                st.session_state["locked_fields"] = locked_fields
                st.rerun()
    else:
        st.subheader("2 · Clarification")
        st.success("All required fields are either filled or skipped.")

    st.divider()

    # ----------------------------------------------------------------
    # Step 3 — Reason
    # ----------------------------------------------------------------
    st.subheader("3 · AI Reasoning")

    report_in_state = st.session_state.get("report")

    if report_in_state is None:
        st.info("Extract a report first.")
    else:
        already_reasoned = report_in_state.get("developer_notes") is not None

        if already_reasoned:
            st.success("AI reasoning has already run on this report.")
        else:
            clarification_pending = len(unlocked_missing) > 0
            if clarification_pending:
                st.warning("Resolve or skip all clarification prompts before running AI reasoning.")

            if st.button("🤖 Run AI Reasoning", disabled=clarification_pending):
                with st.spinner("Running AI reasoning..."):
                    try:
                        before_snapshot = copy.deepcopy(report_in_state)
                        updated_report = reason_and_annotate(report_in_state)
                        st.session_state["report"] = updated_report
                        st.session_state["report_before_reasoning"] = before_snapshot
                        st.rerun()
                    except LLMReasoningError as e:
                        st.error(f"AI reasoning failed: {e}")

        if "report_before_reasoning" in st.session_state:
            with st.expander("🔀 What did AI reasoning change?", expanded=True):
                changes = compute_diff(
                    st.session_state["report_before_reasoning"], st.session_state["report"]
                )
                render_diff(changes)

    st.divider()

    # ----------------------------------------------------------------
    # Step 4 — Preview
    # ----------------------------------------------------------------
    st.subheader("4 · Markdown Preview")

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
            with st.container(border=True):
                st.markdown(st.session_state["final_markdown"])

    st.divider()

    # ----------------------------------------------------------------
    # Step 5 — Send
    # ----------------------------------------------------------------
    st.subheader("5 · QA Review & Send")

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
                if st.button("📧 Approve & Send", type="primary"):
                    if not developer_email or not developer_email.strip():
                        st.warning("Enter a developer email before sending.")
                    else:
                        st.session_state["review_decision"] = review_and_approve("approve")
                        with st.spinner("Sending email..."):
                            result = send_report(final_markdown, developer_email.strip())
                        st.session_state["send_result"] = result
                        st.rerun()
            with col2:
                if st.button("❌ Cancel"):
                    st.session_state["review_decision"] = review_and_approve("cancel")
                    st.rerun()

        elif review_decision is False:
            st.warning("Report cancelled. No email was sent.")
            if st.button("🔄 Start New Report"):
                for key in ("report", "final_markdown", "review_decision", "send_result",
                            "report_before_reasoning", "locked_fields"):
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
                if st.button("🔁 Retry Send"):
                    with st.spinner("Retrying..."):
                        retry_result = send_report(
                            final_markdown,
                            st.session_state.get("developer_email_input", "").strip(),
                        )
                    st.session_state["send_result"] = retry_result
                    st.rerun()

            if st.button("🔄 Start New Report", key="start_new_after_send"):
                for key in ("report", "final_markdown", "review_decision", "send_result",
                            "report_before_reasoning", "locked_fields"):
                    st.session_state.pop(key, None)
                st.rerun()

    st.divider()

    # ----------------------------------------------------------------
    # Dashboard (replaces the raw "Current Report Object" JSON dump)
    # ----------------------------------------------------------------
    st.subheader("📊 Report Dashboard")
    render_report_dashboard(st.session_state["report"], selected_category)