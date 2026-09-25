import json
from pathlib import Path
from config import TEMPLATE_DIR


def _extract_fields(data: dict | list, is_core: bool = False) -> list[str]:
    """Helper to extract a list of field names from parsed JSON data."""
    if isinstance(data, list):
        fields = list(data)
    elif isinstance(data, dict):
        if "fields" in data and isinstance(data["fields"], list):
            fields = list(data["fields"])
        else:
            fields = list(data.keys())
    else:
        fields = []

    if is_core:
        fields = [f for f in fields if f != "category"]

    return fields


def list_categories() -> list[str]:
    """
    Scans {TEMPLATE_DIR}/extensions/*.json for category display names
    (filename stem, e.g. "api" -> "API"), sorted alphabetically, then
    appends "Other" as the last entry unconditionally.
    """
    extensions_dir = Path(TEMPLATE_DIR) / "extensions"
    categories = []

    if extensions_dir.exists() and extensions_dir.is_dir():
        for json_file in extensions_dir.glob("*.json"):
            stem = json_file.stem
            if stem.lower() in ("api", "ui"):
                display_name = stem.upper()
            else:
                display_name = stem.replace("_", " ").title()
            categories.append(display_name)

    categories = sorted(categories)
    categories.append("Other")
    return categories


def resolve_template(category: str) -> dict:
    """
    Args:
        category: lowercase category key, e.g. "api" or "other".
                   "other" (and any value not matching a file in
                   extensions/) skips extension loading entirely.

    Returns:
        {
            "category": "api",              # or "other"
            "required_fields": [<core fields> + <category fields, if any>]
        }

    Raises:
        ValueError: if a field name appears in both core and category
                    lists (schema bug — never raised for "other" since
                    there's nothing to merge)
    """
    cat_key = category.lower().strip().replace(" ", "_")
    base_dir = Path(TEMPLATE_DIR)

    core_file = base_dir / "core_template.json"
    if not core_file.exists():
        raise FileNotFoundError(f"Core template file missing: {core_file}")

    with open(core_file, "r", encoding="utf-8") as f:
        core_data = json.load(f)

    core_fields = _extract_fields(core_data, is_core=True)

    if cat_key == "other":
        return {
            "category": "other",
            "required_fields": core_fields,
        }

    ext_file = base_dir / "extensions" / f"{cat_key}.json"
    if not ext_file.exists():
        return {
            "category": cat_key,
            "required_fields": core_fields,
        }

    with open(ext_file, "r", encoding="utf-8") as f:
        ext_data = json.load(f)

    ext_fields = _extract_fields(ext_data)

    duplicates = [f for f in ext_fields if f in core_fields]
    if duplicates:
        raise ValueError(
            f"Duplicate field(s) found in core and category '{cat_key}' templates: {', '.join(sorted(duplicates))}"
        )

    required_fields = core_fields + ext_fields

    return {
        "category": cat_key,
        "required_fields": required_fields,
    }
