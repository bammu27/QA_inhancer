import streamlit as st
from pipeline.template_loader import resolve_template, list_categories
from pipeline.llm_extraction import extract_fields

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
            except Exception as e:
                st.error(f"Extraction error: {e}")

if "report" in st.session_state:
    st.subheader("Extracted Report Object")
    st.json(st.session_state["report"])
