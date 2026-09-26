import json
import re


def extract_json_object(raw_text: str) -> dict:
    """
    Strips markdown code fences (e.g. ```json ... ```) if present and parses text as JSON object.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    data = json.loads(text.strip())
    if not isinstance(data, dict):
        raise json.JSONDecodeError("JSON root must be an object", text, 0)
    return data
