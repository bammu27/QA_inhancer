# Unit 2 Specification: Raw Text Input & LLM #1 Extraction

## 1. Component Overview
* **Target File:** `pipeline/llm_extraction.py`
* **Function Signature:** `def extract_fields(raw_text: str, template: dict) -> dict:`
* **Primary Objective:** Execute one Groq LLM call over the raw text to extract predefined template fields.

## 2. User Interface Requirements
* The Streamlit frontend must implement an `st.text_area` to collect the raw defect text from the QA tester.
* The UI must include an **"Extract"** button to trigger the extraction function.
* Upon completion of the extraction, the resulting `report_object` must be rendered directly on the screen using `st.json()`.

## 3. LLM Extraction Logic
* The extraction function utilizes the native `groq` Python SDK for fast inference without abstraction layers.
* The prompt must be specifically engineered to return strict JSON that perfectly matches the predefined field-object schema.
* If the LLM successfully locates a field's information within the raw text, it must output the extracted string as the value and tag the source as `tester_provided`.
* If a required template field is absent from the raw text, the LLM must output the value as `null` and tag the source as `missing`.

## 4. Data Validation Rules
* The initial JSON payload returned by Groq must be parsed and strictly validated using **Pydantic**.
* A post-extraction code-level check must run to guarantee that every required field from the loaded template appears exactly once in the output dictionary.
* The pipeline must enforce that every field is explicitly either filled or missing—never both, and never neither.

## 5. Manual Testing Strategy
* Following the project's strategy to conserve token limits, this unit is tested via manual iterative browser testing rather than automated pytest suites.
* The test procedure requires pasting a known sample bug report into the `st.text_area`.
* The output passes verification if all data present in the text is correctly extracted and assigned the `tester_provided` source tag.
* The output passes verification if all data absent from the text is assigned a `null` value with a `missing` source tag.
* The final visual check must confirm that no required template fields were duplicated or dropped during the LLM extraction process.
