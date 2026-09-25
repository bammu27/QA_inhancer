import json
from pathlib import Path
from typing import Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, field_validator
from groq import Groq
from config import (
    GROQ_API_KEY,
    GROQ_MODEL_EXTRACTION,
    GROQ_MAX_TOKENS,
    GROQ_TEMPERATURE,
    TEMPLATE_DIR,
)

CORE_FIELDS = [
    "title",
    "severity",
    "priority",
    "environment",
    "steps_to_reproduce",
    "expected_result",
    "actual_result",
    "frequency",
    "evidence",
]


class FieldObject(BaseModel):
    value: Optional[Union[str, list[str]]] = None
    source: Literal["tester_provided", "ai_annotated", "missing"]

    @field_validator("value", mode="before")
    def format_value(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            cleaned = [str(item).strip() for item in v if str(item).strip()]
            return "\n".join(cleaned) if cleaned else None
        if isinstance(v, str):
            v_str = v.strip()
            return v_str if v_str else None
        return str(v)


def _load_field_descriptions(category: str) -> Dict[str, str]:
    """Helper to load field descriptions from core and extension JSON files."""
    descriptions = {}
    base_dir = Path(TEMPLATE_DIR)

    core_file = base_dir / "core_template.json"
    if core_file.exists():
        try:
            with open(core_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict) and "description" in v:
                            descriptions[k] = v["description"]
        except Exception:
            pass

    if category and category.lower() != "other":
        ext_file = base_dir / "extensions" / f"{category.lower().replace(' ', '_')}.json"
        if ext_file.exists():
            try:
                with open(ext_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, dict) and "description" in v:
                                descriptions[k] = v["description"]
            except Exception:
                pass

    return descriptions


def extract_fields(raw_text: str, template: dict) -> dict:
    """
    Executes one Groq LLM call over raw_text to extract predefined template fields.

    Args:
        raw_text: Freeform bug description entered by QA tester.
        template: Resolved template dict containing 'category' and 'required_fields'.

    Returns:
        report_object:
        {
            "category": "api",
            "core_fields": {
                "title": {"value": "...", "source": "tester_provided"},
                "severity": {"value": null, "source": "missing"}
            },
            "category_fields": {
                "endpoint": {"value": "...", "source": "tester_provided"}
            }
        }
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in environment or .env file.")

    category = template.get("category", "other")
    required_fields = template.get("required_fields", [])
    field_descriptions = _load_field_descriptions(category)

    target_fields_text = []
    for f in required_fields:
        desc = field_descriptions.get(f, "")
        if desc:
            target_fields_text.append(f"- '{f}': {desc}")
        else:
            target_fields_text.append(f"- '{f}'")
    fields_formatted = "\n".join(target_fields_text)

    system_prompt = f"""You are an expert QA bug report extraction assistant.
Your job is to read raw, unstructured bug report text provided by a QA tester and extract specific fields.

TARGET FIELDS TO EXTRACT:
{fields_formatted}

EXTRACTION RULES:
1. For each target field listed above, inspect the raw text thoroughly.
2. If explicit or strongly implied information for the field is present in the raw text:
   - "value": string (or list of step strings for steps_to_reproduce) containing the exact extracted content.
   - "source": "tester_provided"
3. If the field is absent or not mentioned in the raw text:
   - "value": null
   - "source": "missing"
4. NEVER invent or fabricate facts not supported by the raw text.
5. Every single target field name listed above MUST appear in the output.

Output MUST be a JSON object containing an "extracted_fields" dictionary mapping field names to field objects.
Example output format:
{{
  "extracted_fields": {{
    "title": {{"value": "Login button 500 error", "source": "tester_provided"}},
    "severity": {{"value": null, "source": "missing"}}
  }}
}}"""

    user_prompt = f"RAW DEFECT TEXT:\n\"\"\"\n{raw_text}\n\"\"\""

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
        raise RuntimeError(f"Groq API call failed: {e}")

    content = response.choices[0].message.content
    try:
        raw_json = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse LLM output as JSON: {e}\nRaw output: {content}")

    extracted_data = raw_json.get("extracted_fields", raw_json)

    validated_fields: Dict[str, Dict[str, Any]] = {}

    for field_name in required_fields:
        raw_field_obj = extracted_data.get(field_name) if isinstance(extracted_data, dict) else None

        if not raw_field_obj or not isinstance(raw_field_obj, dict):
            val = None
            src = "missing"
        else:
            val = raw_field_obj.get("value")
            src = raw_field_obj.get("source")

        if val is not None and str(val).strip() != "":
            clean_val = str(val).strip() if not isinstance(val, list) else "\n".join([str(x).strip() for x in val if str(x).strip()])
            if clean_val:
                pydantic_obj = FieldObject(value=clean_val, source="tester_provided")
            else:
                pydantic_obj = FieldObject(value=None, source="missing")
        else:
            pydantic_obj = FieldObject(value=None, source="missing")

        validated_fields[field_name] = {
            "value": pydantic_obj.value,
            "source": pydantic_obj.source,
        }

    core_fields_dict = {}
    category_fields_dict = {}

    for field_name in required_fields:
        field_data = validated_fields[field_name]
        if field_name in CORE_FIELDS:
            core_fields_dict[field_name] = field_data
        else:
            category_fields_dict[field_name] = field_data

    return {
        "category": category,
        "core_fields": core_fields_dict,
        "category_fields": category_fields_dict,
    }
