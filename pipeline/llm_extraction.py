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

# Fields where the LLM is allowed to reason/infer from context rather than
# requiring literal text. Anything not in this set must be extracted verbatim
# (or marked missing) — never inferred.
#
# expected_result is included because testers almost never write "Expected: X"
# explicitly — it's implied by the nature of the bug (e.g. a checkout endpoint
# throwing a 500 implies "checkout should complete successfully"). Treating it
# as strict caused it to come back missing in most real-world reports.

SEMANTIC_FIELDS = {
    "severity",
    "priority",
    "frequency",
    "expected_result",
}


from models.schemas import FieldObject, ReportObject


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


def _format_field_list(fields: list[str], descriptions: Dict[str, str]) -> str:
    lines = []
    for f in fields:
        desc = descriptions.get(f, "")
        lines.append(f"- '{f}': {desc}" if desc else f"- '{f}'")
    return "\n".join(lines)


def extract_fields(raw_text: str, template: dict) -> dict:
    """
    Executes one Groq LLM call over raw_text to extract predefined template fields.

    Strict fields are extracted verbatim from the text (source="tester_provided")
    or marked missing. Semantic fields (see SEMANTIC_FIELDS) may additionally be
    inferred from context when not stated explicitly (source="ai_annotated").

    Args:
        raw_text: Freeform bug description entered by QA tester.
        template: Resolved template dict containing 'category' and 'required_fields'.

    Returns:
        report_object:
        {
            "category": "api",
            "core_fields": {
                "title": {"value": "...", "source": "tester_provided"},
                "severity": {"value": "High", "source": "ai_annotated"},
                "priority": {"value": null, "source": "missing"}
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

    strict_fields = [f for f in required_fields if f not in SEMANTIC_FIELDS]
    semantic_fields = [f for f in required_fields if f in SEMANTIC_FIELDS]

    strict_block = _format_field_list(strict_fields, field_descriptions)
    semantic_block = _format_field_list(semantic_fields, field_descriptions)

    semantic_section = ""
    if semantic_fields:
        semantic_section = f"""
SEMANTIC FIELDS (reasoning permitted):
{semantic_block}

For these fields ONLY, you may infer a reasonable value from context even if
it is not stated explicitly — e.g. "the app crashes for every user on login"
implies high severity. Base every inference strictly on details present in
the raw text; do not use outside/world knowledge.
- If the tester explicitly stated the value: "source": "tester_provided"
- If you inferred it from context: "source": "ai_annotated"
- If there is not enough context to infer it at all: "value": null, "source": "missing"
"""

    FORMAT_GUIDANCE = """
INPUT FORMAT WARNING:
Raw bug text almost never looks like clean prose. It may be a copy-pasted log
dump, a JSON blob, a chat transcript, a ticket-tool export, or a mix of all
three, with arbitrary or inconsistent section labels (e.g. "TRACELOG",
"ENVDATA", "REPRO_STEPS_TRACELOG", "<<<PAYLOAD>>>", or no labels at all). Do
NOT rely on section headers matching field names literally — match by MEANING,
regardless of what a block happens to be titled or how it's punctuated.

Below are common real-world shapes for the trickiest fields. These are
illustrations of the PATTERN to recognize, not an exhaustive list — the same
logic applies to any field, in any format not shown here.

— steps_to_reproduce —
Look for ANY sequence of user/system actions and their results: numbered
fragments ("step1:", "step2:"), arrow chains ("click X -> response Y"), a
chat-style walkthrough, or a list of UI interactions. Convert whatever you
find into a clean ordered list, one action+result per list item.
    Input:  "step1: add_to_cart -> payload {...} -> 200 ok
             step2: click checkout -> POST /checkout -> 500 error"
    Output: ["Added item to cart; received 200 OK",
             "Clicked checkout, triggering POST /checkout; received 500 Internal Server Error"]
Ignore blocks that are clearly speculation or debugging hypotheses rather
than actions actually taken (e.g. titled "RANDOM TROUBLESHOOTING NOTES",
"RANTS", "possible causes") — never treat those as steps_to_reproduce, even
if they mention something the tester did or suspects.

— environment —
Often arrives as a terse key=value or key: value line rather than prose, and
the keys are rarely "OS" / "Browser" verbatim.
    Input:  'ENVDATA:: OS="Windows 11" UA="Mozilla/5.0 ..." BROWSER="Chrome 122"'
    Output: "OS: Windows 11, Browser: Chrome 122, UA: Mozilla/5.0 ..."

— evidence —
This is the one field where raw, messy diagnostic text (stack traces, log
lines, HAR-style network entries) IS the correct value — do not clean it up
into prose, just pull the relevant raw fragment(s) as-is.

— expected_result (semantic field) —
This is almost never stated explicitly. Infer it from what a working version
of the described flow would do, using ONLY the flow/feature/endpoint actually
named in the text — never generic assumptions.
    Input describes: a POST to /api/v1/checkout returning 500 instead of
                      completing the order
    Output: "Checkout request should complete successfully and return a
             success response" (source: "ai_annotated")
If the text doesn't name what the feature was supposed to do at all (no
endpoint, no described user goal), leave it missing rather than guessing.

SELF-CHECK before you finalize: go back through every target field name in
the lists below one more time and confirm you didn't skip one just because
its content wasn't under a header that matched the field's name.
"""

    system_prompt = f"""You are an expert QA bug report extraction assistant.
Your job is to read raw, unstructured bug report text provided by a QA tester and extract specific fields.
{FORMAT_GUIDANCE}
STRICT FIELDS (literal extraction only):
{strict_block}

For these fields, extract ONLY information explicitly or near-explicitly present
in the raw text. NEVER invent or infer facts not supported by the raw text.
- "value": string (or list of step strings for steps_to_reproduce) containing the exact extracted content.
- "source": "tester_provided"
- If absent: "value": null, "source": "missing"
{semantic_section}
GENERAL RULES:
1. Inspect the raw text thoroughly for every target field, regardless of formatting or section labels — see INPUT FORMAT WARNING above.
2. Every single target field name listed above MUST appear in the output.
3. Never fabricate information that has no basis anywhere in the raw text, even for semantic fields.

Output MUST be a JSON object containing an "extracted_fields" dictionary mapping field names to field objects.
Example output format:
{{
  "extracted_fields": {{
    "title": {{"value": "Login button 500 error", "source": "tester_provided"}},
    "steps_to_reproduce": {{"value": ["Step one text", "Step two text"], "source": "tester_provided"}},
    "environment": {{"value": "OS: Windows 11, Browser: Chrome 122", "source": "tester_provided"}},
    "expected_result": {{"value": "Checkout should complete successfully", "source": "ai_annotated"}},
    "severity": {{"value": "High", "source": "ai_annotated"}},
    "priority": {{"value": null, "source": "missing"}}
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

        val = None
        src = "missing"
        if isinstance(raw_field_obj, dict):
            val = raw_field_obj.get("value")
            src = raw_field_obj.get("source", "missing")

        if val is not None:
            clean_val = (
                "\n".join([str(x).strip() for x in val if str(x).strip()])
                if isinstance(val, list)
                else str(val).strip()
            )
        else:
            clean_val = None

        if clean_val:
            # Honor the LLM's reported source, but never let a strict field
            # come back as ai_annotated — clamp it defensively.
            if src not in ("tester_provided", "ai_annotated"):
                src = "tester_provided"
            if field_name not in SEMANTIC_FIELDS and src == "ai_annotated":
                src = "tester_provided"
            pydantic_obj = FieldObject(value=clean_val, source=src)
        else:
            pydantic_obj = FieldObject(value=None, source="missing")

        validated_fields[field_name] = {
            "value": pydantic_obj.value,
            "source": pydantic_obj.source,
        }

    report_obj = ReportObject(
        category=category,
        fields={k: FieldObject(**v) for k, v in validated_fields.items()}
    )
    return report_obj.model_dump()