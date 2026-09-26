import json
from typing import Dict, List, Set, Tuple
from groq import Groq
from config import (
    GROQ_API_KEY,
    GROQ_MODEL_EXTRACTION,
    GROQ_MAX_TOKENS,
    GROQ_TEMPERATURE,
)


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
    if not missing_fields:
        return {}

    cleaned_text = user_input_text.strip()
    if not cleaned_text:
        return {}

    lowered = cleaned_text.lower()
    if lowered in {"skip", "unknown", "pass", "don't know", "dont know", "n/a", "none"}:
        return {}

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in environment or .env file.")

    fields_list_str = "\n".join([f"- '{f}'" for f in missing_fields])

    system_prompt = f"""You are an expert QA defect report clarification assistant.
Your task is to parse a QA tester's natural language input specifically to extract values for a set of missing fields.

TARGET MISSING FIELDS TO EXTRACT:
{fields_list_str}

RULES:
1. Parse the user's input text ONLY for the target missing fields listed above.
2. For each field in the target list:
   - If the user provides explicit details or values for that field, extract it as a clear string value.
   - If the user explicitly states they don't know, pass, skip, or if the field is unaddressed or absent in the text, return null for that field value.
3. Do NOT invent, assume, or fabricate any facts not in the user's input.
4. Output strict JSON containing a single key "clarifications" mapping field names to extracted string values or null.

Example Output format:
{{
  "clarifications": {{
    "severity": "High",
    "priority": null,
    "steps_to_reproduce": "1. Go to settings\\n2. Click save"
  }}
}}"""

    user_prompt = f"USER CLARIFICATION INPUT:\n\"\"\"\n{cleaned_text}\n\"\"\""

    client = Groq(api_key=GROQ_API_KEY)

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL_EXTRACTION,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=GROQ_TEMPERATURE,
            max_tokens=GROQ_MAX_TOKENS,
        )
    except Exception as e:
        raise RuntimeError(f"Groq API call failed during clarification extraction: {e}")

    content = response.choices[0].message.content
    try:
        raw_json = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse LLM clarification output as JSON: {e}\nRaw output: {content}")

    clarifications = raw_json.get("clarifications", raw_json)

    extracted_results: dict[str, str] = {}

    if isinstance(clarifications, dict):
        for field in missing_fields:
            val = clarifications.get(field)
            if val is not None:
                if isinstance(val, list):
                    clean_val = "\n".join([str(x).strip() for x in val if str(x).strip()])
                else:
                    clean_val = str(val).strip()

                # Filter out explicit skip/unknown string values returned by LLM
                if clean_val.lower() in {"unknown", "skip", "pass", "don't know", "dont know", "n/a", "null", "none"}:
                    clean_val = ""

                if clean_val:
                    extracted_results[field] = clean_val

    return extracted_results


def get_missing_fields(report: dict) -> list[str]:
    """Helper to extract all field names in report tagged as source='missing' or value=None."""
    missing = []
    fields = report.get("fields")
    if isinstance(fields, dict):
        for field_name, field_obj in fields.items():
            if isinstance(field_obj, dict):
                if field_obj.get("source") == "missing" or field_obj.get("value") is None:
                    missing.append(field_name)
        return missing

    for section_name in ["core_fields", "category_fields"]:
        section = report.get(section_name, {})
        if isinstance(section, dict):
            for field_name, field_obj in section.items():
                if isinstance(field_obj, dict):
                    if field_obj.get("source") == "missing" or field_obj.get("value") is None:
                        missing.append(field_name)
    return missing


def get_unlocked_missing_fields(report: dict, locked_fields: set | list) -> list[str]:
    """Helper to extract missing fields that are not in locked_fields."""
    locked_set = set(locked_fields) if locked_fields else set()
    missing = get_missing_fields(report)
    return [f for f in missing if f not in locked_set]


def apply_clarifications(
    report: dict,
    prompted_fields: list[str],
    extracted_clarifications: dict[str, str],
    locked_fields: set[str]
) -> tuple[dict, set[str]]:
    """
    Updates the report object with extracted clarification values,
    and locks any prompted fields that were not addressed or explicitly skipped.
    """
    fields = report.get("fields")
    if isinstance(fields, dict):
        for field_name, field_obj in fields.items():
            if field_name in prompted_fields:
                if field_name in extracted_clarifications and extracted_clarifications[field_name]:
                    field_obj["value"] = extracted_clarifications[field_name]
                    field_obj["source"] = "tester_provided"
                else:
                    field_obj["value"] = None
                    field_obj["source"] = "missing"
                    locked_fields.add(field_name)
    else:
        for section_name in ["core_fields", "category_fields"]:
            section = report.get(section_name, {})
            if isinstance(section, dict):
                for field_name, field_obj in section.items():
                    if field_name in prompted_fields:
                        if field_name in extracted_clarifications and extracted_clarifications[field_name]:
                            field_obj["value"] = extracted_clarifications[field_name]
                            field_obj["source"] = "tester_provided"
                        else:
                            # Unaddressed or skipped fields stay missing and become locked
                            field_obj["value"] = None
                            field_obj["source"] = "missing"
                            locked_fields.add(field_name)

    return report, locked_fields

