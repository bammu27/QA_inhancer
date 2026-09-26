import copy
import json
from pydantic import ValidationError

from models.schemas import ReportObject, FieldObject, DeveloperNotes
from utils.groq_client import chat_completion
from utils.json_utils import extract_json_object
from utils.diff_check import assert_tester_provided_unchanged, TesterProvidedMutationError
from prompts.reasoning_prompt import build_reasoning_messages
import config


class LLMReasoningError(Exception):
    pass


def reason_and_annotate(report: dict) -> dict:
    original_fields = copy.deepcopy(report["fields"])

    # Guard: reject if this report has already been through reasoning.
    # developer_notes is only ever written by reason_and_annotate, so its
    # presence is the authoritative idempotency signal. Checking for
    # ai_annotated fields is NOT sufficient because the extraction step
    # legitimately produces ai_annotated values for semantic fields
    # (severity, priority, frequency, expected_result).
    if report.get("developer_notes") is not None:
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
    #    between original and new, byte-for-byte.
    try:
        assert_tester_provided_unchanged(original_fields, new_fields)
    except TesterProvidedMutationError as e:
        raise LLMReasoningError(str(e)) from e

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
