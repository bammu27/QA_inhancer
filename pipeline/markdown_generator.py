"""
Unit 5 — Markdown Generator
Pure formatting: no Groq call, no file I/O, no network access.
Takes the fully-reasoned report dict produced by Unit 4 and renders it
into a single Markdown string. Same input always produces the same output.
"""


class MarkdownGenerationError(Exception):
    pass


def _format_label(field_name: str) -> str:
    """
    snake_case -> Title Case With Spaces.
    "http_method"        -> "Http Method"
    "steps_to_reproduce" -> "Steps To Reproduce"

    Deliberately NOT special-casing acronyms (no "HTTP Method",
    no "API endpoint") — a fixed acronym-exception list is a source of
    silent drift as fields are added later. Plain Title Case only.
    """
    return field_name.replace("_", " ").title()


def _render_field_line(field_name: str, field: dict) -> str:
    """Render a single field as one Markdown line."""
    label = _format_label(field_name)
    source = field["source"]
    value = field["value"]

    if source == "missing":
        return f"**{label}:** _Not provided_"
    elif source == "tester_provided":
        return f"**{label}:** {value}"
    elif source == "ai_annotated":
        return f"**{label}:** {value} _(AI annotated)_"
    else:
        raise MarkdownGenerationError(
            f'Field "{field_name}" has unrecognized source "{source}".'
        )


def render_markdown(report: dict) -> str:
    if "fields" not in report or not isinstance(report["fields"], dict):
        raise MarkdownGenerationError('report["fields"] is missing or not a dict.')

    dev_notes = report.get("developer_notes")
    if dev_notes is None:
        raise MarkdownGenerationError("developer_notes is None.")

    fields = report["fields"]

    def fmt(name):
        return name.replace("_", " ").title()

    def val(field):
        if field["source"] == "missing":
            return "_Not provided_"
        return field["value"]

    def is_ai(field):
        return field["source"] == "ai_annotated"

    summary_keys = [k for k in ("severity", "priority", "environment", "frequency") if k in fields]
    detail_keys = [k for k in fields if k not in summary_keys and k != "title"]

    ai_count = sum(1 for f in fields.values() if f["source"] == "ai_annotated")

    lines = [f"# 🐞 {fmt(report['category'])} Defect Report", ""]

    if "title" in fields:
        lines += [f"### {fields['title']['value']}", ""]

    # Legend — only shown if at least one field was AI-annotated
    if ai_count:
        lines += [
            "> ⚠️ **Heads up:** fields marked 🤖 **AI-inferred** below were not "
            "confirmed by the tester — the AI filled them in based on context. "
            "Verify before relying on them.",
            "",
        ]

    if summary_keys:
        lines.append("| " + " | ".join(fmt(k) for k in summary_keys) + " |")
        lines.append("|" + "---|" * len(summary_keys))
        row = []
        for k in summary_keys:
            f = fields[k]
            cell = val(f)
            if is_ai(f):
                cell += " 🤖"
            row.append(cell)
        lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    lines.append("---")
    for k in detail_keys:
        f = fields[k]
        lines.append(f"**{fmt(k)}**")
        if is_ai(f):
            lines.append("")
            lines.append(f"> 🤖 **AI-inferred** — not confirmed by tester")
            lines.append(f"> {val(f)}")
        else:
            lines.append("")
            lines.append(val(f))
        lines.append("")

    lines += ["---", "## 🛠️ Developer Notes", "", dev_notes["description"], ""]

    fixes = dev_notes.get("common_fixes", [])
    if fixes:
        lines.append("**Suggested fixes:**")
        lines += [f"- {f}" for f in fixes]
    else:
        lines.append("_No fixes suggested._")

    return "\n".join(lines)