import json


def build_reasoning_messages(report: dict) -> list[dict]:
    fields = report["fields"]

    tester_provided = {
        k: v["value"] for k, v in fields.items() if v["source"] == "tester_provided"
    }
    missing = [k for k, v in fields.items() if v["source"] == "missing"]

    system_prompt = (
        "You are a defect-report reasoning assistant. You are given a "
        "partially-filled bug report: some fields are already confirmed by "
        "a human tester, and some fields are missing. Your job is to: "
        "(1) infer values for missing fields ONLY where the confirmed "
        "fields make a reasonable inference possible, and (2) write a "
        "short developer-facing summary and a list of common fixes. "
        "You must NEVER invent a change to, or restate a modified version "
        "of, any field that is already confirmed — those are provided "
        "verbatim below for context only, not for you to edit. "
        "You respond with ONLY a single JSON object — no markdown code "
        "fences, no preamble, no explanation."
    )

    user_prompt = (
        f"Bug category: {report['category']}\n\n"
        f"Confirmed fields (context only — do NOT include these in your "
        f"output, they are already final):\n"
        f"{json.dumps(tester_provided, indent=2)}\n\n"
        f"Fields still missing (infer a value ONLY if the confirmed "
        f"fields above genuinely support a specific inference; otherwise "
        f'leave as null — do not guess vague filler like "unknown" or '
        f'"N/A"):\n'
        f"{json.dumps(missing)}\n\n"
        f"Return a JSON object with exactly this shape:\n"
        f'{{\n'
        f'  "annotated_fields": {{"<field_name>": "<inferred value or null>"}},\n'
        f'  "developer_notes": {{\n'
        f'    "description": "<2-4 sentence summary for the developer>",\n'
        f'    "common_fixes": ["<short suggestion>", "..."]\n'
        f'  }}\n'
        f'}}\n\n'
        f"Rules:\n"
        f'1. "annotated_fields" must contain exactly the keys listed in '
        f'"Fields still missing" above — no more, no fewer, and none of '
        f"the confirmed field names.\n"
        f'2. Set a field\'s value to null in "annotated_fields" if you '
        f"cannot make a genuine, specific inference — an empty guess is "
        f"worse than admitting you don\'t know.\n"
        f'3. "common_fixes" may be an empty list if nothing applies, but '
        f"the key must be present.\n"
        f"4. Output ONLY the JSON object. No other text."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
