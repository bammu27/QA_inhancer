import copy
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

st.set_page_config(page_title="Defect Description Enhancer", layout="centered")
st.title("Defect Description Enhancer")

categories = list_categories()  # always non-empty: "Other" is guaranteed

selected_category = st.selectbox("Bug category", categories)

try:
    template = resolve_template(selected_category.lower())
except ValueError as e:
    st.error(f"Template schema error: {e}")
    st.stop()

st.subheader("Raw Defect Description")
raw_text = st.text_area(
    "Paste raw defect report text here:",
    height=200,
    placeholder="e.g. When performing POST /api/v1/checkout on Chrome/Win11, getting HTTP 500 Internal Server Error every time. Payload sent was {'cart_id': 123}. Expected 200 OK."
)

if st.button("Extract", type="primary"):
    if not raw_text.strip():
        st.warning("Please enter raw defect text before clicking Extract.")
    else:
        with st.spinner("Extracting fields with Groq LLM..."):
            try:
                report = extract_fields(raw_text, template)
                st.session_state["report"] = report
                st.session_state["locked_fields"] = set()
                st.session_state.pop("report_before_reasoning", None)
            except Exception as e:
                st.error(f"Extraction error: {e}")

if "report" in st.session_state:
    report = st.session_state["report"]
    locked_fields = st.session_state.get("locked_fields", set())

    unlocked_missing = get_unlocked_missing_fields(report, locked_fields)

    st.divider()

    if unlocked_missing:
        st.subheader("Clarification Loop")
        formatted_missing = [f"`{f}`" for f in unlocked_missing]
        st.info(f"The following required fields are missing and unlocked ({len(unlocked_missing)}): " + ", ".join(formatted_missing))

        clarification_text = st.text_area(
            "Describe anything you know about the missing fields",
            height=120,
            placeholder="e.g. Priority is High. Environment OS is Windows 11."
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Submit clarification", type="primary"):
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
            if st.button("Skip remaining fields"):
                for field in unlocked_missing:
                    locked_fields.add(field)
                st.session_state["locked_fields"] = locked_fields
                st.rerun()
    else:
        st.success("Clarification Complete: All required fields are either filled or locked.")
        st.info("Pipeline ready for LLM #2 (Reasoning & Annotation).")

    st.divider()
    st.subheader("AI Reasoning")

    report_in_state = st.session_state.get("report")

    if report_in_state is None:
        st.info("Extract a report first.")
    else:
        already_reasoned = report_in_state.get("developer_notes") is not None

        if already_reasoned:
            st.info("AI reasoning has already run on this report.")
        else:
            clarification_pending = len(unlocked_missing) > 0

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
                        st.rerun()
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
                st.success(f"\u2705 Report sent to {st.session_state.get('developer_email_input', '')}.")
            else:
                st.error(f"\u274c Send failed: {result['error']}")
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

    st.divider()
    st.subheader("Current Report Object")
    st.json(st.session_state["report"])
