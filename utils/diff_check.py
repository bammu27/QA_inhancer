class TesterProvidedMutationError(Exception):
    pass


def assert_tester_provided_unchanged(original_fields: dict, new_fields: dict) -> None:
    """
    Raises TesterProvidedMutationError, naming every offending field, if
    any field that was source == "tester_provided" in original_fields has
    a different "value" or a different "source" in new_fields.

    This must be called with the ORIGINAL pre-LLM-#2 fields dict and the
    CANDIDATE post-LLM-#2 fields dict, both in the same
    {field_name: {"value": ..., "source": ...}} shape.
    """
    violations = []
    for field_name, original in original_fields.items():
        if original["source"] != "tester_provided":
            continue
        new = new_fields.get(field_name)
        if new is None:
            violations.append(f'{field_name}: dropped entirely')
            continue
        if new["source"] != "tester_provided" or new["value"] != original["value"]:
            violations.append(
                f'{field_name}: was {original!r}, became {new!r}'
            )

    if violations:
        raise TesterProvidedMutationError(
            "tester_provided fields were mutated by LLM #2 reasoning: "
            + "; ".join(violations)
        )
